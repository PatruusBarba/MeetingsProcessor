"""
Offline live streaming ASR using NVIDIA Parakeet TDT V3 (NeMo).

Implements the same streaming loop as NeMo's
examples/asr/asr_chunked_inference/rnnt/speech_to_text_streaming_infer_rnnt.py
adapted for incremental microphone-style audio (batch size 1).
"""

from __future__ import annotations

import array
import copy
import os
import queue
import threading
from typing import Callable

import numpy as np

# NeMo recommends this before importing torch (reduces GPU memory fragmentation)
_alloc = os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "")
if "expandable_segments" not in _alloc:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = (
        _alloc + ",expandable_segments:True" if _alloc else "expandable_segments:True"
    )


def _pcm16_to_f32_mono(mono_bytes: bytes) -> np.ndarray:
    if not mono_bytes:
        return np.array([], dtype=np.float32)
    a = array.array("h")
    a.frombytes(mono_bytes)
    x = np.asarray(a, dtype=np.float32) / 32768.0
    return np.clip(x, -1.0, 1.0)


def _resample_linear(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if x.size == 0 or src_sr == dst_sr:
        return x.astype(np.float32, copy=False)
    ratio = dst_sr / src_sr
    n_dst = max(1, int(len(x) * ratio))
    t_src = np.linspace(0.0, len(x) - 1, num=len(x), dtype=np.float64)
    t_dst = np.linspace(0.0, len(x) - 1, num=n_dst, dtype=np.float64)
    return np.interp(t_dst, t_src, x.astype(np.float64)).astype(np.float32)


def _make_divisible_by(num: int, factor: int) -> int:
    return (num // factor) * factor


class _Float32ChunkBuffer:
    """Append-only mono float32 storage with slice read without O(n) concat per append."""

    __slots__ = ("_parts", "total")

    def __init__(self) -> None:
        self._parts: list[np.ndarray] = []
        self.total = 0

    def append(self, x: np.ndarray) -> None:
        if x.size == 0:
            return
        self._parts.append(x.astype(np.float32, copy=False))
        self.total += int(x.shape[0])

    def slice(self, start: int, end: int) -> np.ndarray:
        if start >= end or start >= self.total:
            return np.array([], dtype=np.float32)
        end = min(end, self.total)
        out: list[np.ndarray] = []
        pos = 0
        for p in self._parts:
            pl = len(p)
            nxt = pos + pl
            if nxt <= start:
                pos = nxt
                continue
            if pos >= end:
                break
            a = max(0, start - pos)
            b = min(pl, end - pos)
            if a < b:
                out.append(p[a:b])
            pos = nxt
        if not out:
            return np.array([], dtype=np.float32)
        if len(out) == 1:
            return out[0]
        return np.concatenate(out, axis=0)


class ParakeetLiveTranscriberThread(threading.Thread):
    """
    Consumes mono int16 PCM at ``sample_rate``; resamples to model rate (16 kHz).
    Puts incremental transcript updates (full hypothesis text) into ``text_queue``.
    Sends None sentinel when stream ends.
    """

    def __init__(
        self,
        audio_queue: queue.Queue,
        sample_rate: int,
        text_queue: queue.Queue,
        pretrained_name: str,
        device_str: str,
        torch_dtype_str: str,
        chunk_secs: float,
        left_context_secs: float,
        right_context_secs: float,
        on_model_loading: Callable[[], None] | None,
        on_error: Callable[[str], None] | None,
    ) -> None:
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.sample_rate = sample_rate
        self.text_queue = text_queue
        self.pretrained_name = pretrained_name or "nvidia/parakeet-tdt-0.6b-v3"
        self.device_str = (device_str or "cpu").lower()
        self.torch_dtype_str = (torch_dtype_str or "float32").lower()
        self.chunk_secs = float(chunk_secs)
        self.left_context_secs = float(left_context_secs)
        self.right_context_secs = float(right_context_secs)
        self.on_model_loading = on_model_loading
        self.on_error = on_error

    def run(self) -> None:
        try:
            import torch
            from omegaconf import OmegaConf, open_dict
            import nemo.collections.asr as nemo_asr
            from nemo.collections.asr.models import EncDecRNNTModel
            from nemo.collections.asr.parts.submodules.rnnt_decoding import RNNTDecodingConfig
            from nemo.collections.asr.parts.submodules.transducer_decoding.label_looping_base import (
                GreedyBatchedLabelLoopingComputerBase,
            )
            from nemo.collections.asr.parts.utils.rnnt_utils import batched_hyps_to_hypotheses
            from nemo.collections.asr.parts.utils.streaming_utils import (
                ContextSize,
                StreamingBatchedAudioBuffer,
            )
        except ImportError as e:
            if self.on_error:
                self.on_error(
                    "NeMo ASR not installed. For Parakeet streaming run:\n"
                    "  pip install 'nemo_toolkit[asr]'\n"
                    f"({e})"
                )
            return

        if self.on_model_loading:
            self.on_model_loading()

        device = torch.device("cuda:0" if self.device_str == "cuda" else "cpu")
        if self.device_str == "cuda" and not torch.cuda.is_available():
            if self.on_error:
                self.on_error("CUDA requested but not available. Set transcription device to CPU in Settings.")
            return

        dtype_map = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
        compute_dtype = dtype_map.get(self.torch_dtype_str, torch.float32)
        if compute_dtype == torch.bfloat16 and device.type == "cpu":
            compute_dtype = torch.float32

        try:
            asr_model = nemo_asr.models.ASRModel.from_pretrained(model_name=self.pretrained_name)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Failed to load Parakeet model: {e}")
            return

        if not isinstance(asr_model, EncDecRNNTModel):
            if self.on_error:
                self.on_error(f"Expected EncDecRNNTModel, got {type(asr_model).__name__}")
            return

        model_cfg = copy.deepcopy(asr_model._cfg)
        OmegaConf.set_struct(model_cfg.preprocessor, False)
        model_cfg.preprocessor.dither = 0.0
        model_cfg.preprocessor.pad_to = 0
        if model_cfg.preprocessor.normalize != "per_feature":
            if self.on_error:
                self.on_error("This Parakeet build expects per_feature normalization.")
            return
        OmegaConf.set_struct(model_cfg.preprocessor, True)

        asr_model.freeze()
        asr_model = asr_model.to(device)
        asr_model.to(compute_dtype)
        asr_model.preprocessor.featurizer.dither = 0.0
        asr_model.preprocessor.featurizer.pad_to = 0
        asr_model.eval()

        dec_cfg = RNNTDecodingConfig()
        dec_cfg.model_type = "tdt"
        dec_cfg.strategy = "greedy_batch"
        dec_cfg.greedy.loop_labels = True
        dec_cfg.tdt_include_token_duration = False
        dec_cfg.greedy.preserve_alignments = False
        dec_cfg.fused_batch_size = -1
        dec_cfg.beam.return_best_hypothesis = True

        asr_model.change_decoding_strategy(dec_cfg)

        decoding_computer: GreedyBatchedLabelLoopingComputerBase = asr_model.decoding.decoding.decoding_computer

        audio_sample_rate = int(model_cfg.preprocessor["sample_rate"])
        feature_stride_sec = float(model_cfg.preprocessor["window_stride"])
        features_per_sec = 1.0 / feature_stride_sec
        encoder_subsampling_factor = int(asr_model.encoder.subsampling_factor)

        features_frame2audio_samples = _make_divisible_by(
            int(audio_sample_rate * feature_stride_sec), factor=encoder_subsampling_factor
        )
        encoder_frame2audio_samples = features_frame2audio_samples * encoder_subsampling_factor

        context_encoder_frames = ContextSize(
            left=int(self.left_context_secs * features_per_sec / encoder_subsampling_factor),
            chunk=int(self.chunk_secs * features_per_sec / encoder_subsampling_factor),
            right=int(self.right_context_secs * features_per_sec / encoder_subsampling_factor),
        )
        context_samples = ContextSize(
            left=context_encoder_frames.left * encoder_subsampling_factor * features_frame2audio_samples,
            chunk=context_encoder_frames.chunk * encoder_subsampling_factor * features_frame2audio_samples,
            right=context_encoder_frames.right * encoder_subsampling_factor * features_frame2audio_samples,
        )

        batch_size = 1
        buffer = StreamingBatchedAudioBuffer(
            batch_size=batch_size,
            context_samples=context_samples,
            dtype=torch.float32,
            device=device,
        )

        audio_buf = _Float32ChunkBuffer()
        left_sample = 0
        right_sample = 0
        rest_audio_lengths = torch.zeros(1, dtype=torch.long, device=device)
        state = None
        current_batched_hyps = None
        last_text = ""

        def flush_hypothesis() -> None:
            nonlocal last_text
            if current_batched_hyps is None:
                return
            hyps = batched_hyps_to_hypotheses(current_batched_hyps, None, batch_size=batch_size)
            if not hyps:
                return
            hyp = hyps[0]
            hyp.text = asr_model.tokenizer.ids_to_text(hyp.y_sequence.tolist())
            t = (hyp.text or "").strip()
            if t and t != last_text:
                last_text = t
                self.text_queue.put(t)

        def consume_streaming(T: int, stream_end: bool) -> None:
            """Match NeMo speech_to_text_streaming_infer_rnnt inner loop (batch size 1)."""
            nonlocal left_sample, right_sample, rest_audio_lengths, state, current_batched_hyps
            if T == 0:
                return
            # Remaining samples not yet advanced past (grows when T increases mid-stream)
            rest_audio_lengths[0] = T - left_sample
            if right_sample == 0:
                right_sample = min(context_samples.chunk + context_samples.right, T)

            with torch.no_grad(), torch.inference_mode():
                while left_sample < T:
                    chunk_length = min(right_sample, T) - left_sample
                    if chunk_length <= 0:
                        break
                    is_last_chunk_batch = chunk_length >= rest_audio_lengths
                    is_last_chunk = stream_end and (right_sample >= T)
                    chunk_lengths_batch = torch.where(
                        is_last_chunk_batch,
                        rest_audio_lengths,
                        torch.full_like(rest_audio_lengths, fill_value=chunk_length),
                    )

                    slice_np = audio_buf.slice(left_sample, right_sample)
                    if slice_np.size == 0:
                        break
                    audio_batch = torch.from_numpy(slice_np).to(device=device, dtype=torch.float32).unsqueeze(0)

                    buffer.add_audio_batch_(
                        audio_batch,
                        audio_lengths=chunk_lengths_batch,
                        is_last_chunk=is_last_chunk,
                        is_last_chunk_batch=is_last_chunk_batch,
                    )

                    encoder_output, encoder_output_len = asr_model(
                        input_signal=buffer.samples,
                        input_signal_length=buffer.context_size_batch.total(),
                    )
                    encoder_output = encoder_output.transpose(1, 2)

                    encoder_context = buffer.context_size.subsample(factor=encoder_frame2audio_samples)
                    encoder_context_batch = buffer.context_size_batch.subsample(
                        factor=encoder_frame2audio_samples
                    )
                    encoder_output = encoder_output[:, encoder_context.left :]

                    chunk_batched_hyps, _, state = decoding_computer(
                        x=encoder_output,
                        out_len=torch.where(
                            is_last_chunk_batch,
                            encoder_output_len - encoder_context_batch.left,
                            encoder_context_batch.chunk,
                        ),
                        prev_batched_state=state,
                        multi_biasing_ids=None,
                    )

                    if current_batched_hyps is None:
                        current_batched_hyps = chunk_batched_hyps
                    else:
                        current_batched_hyps.merge_(chunk_batched_hyps)

                    flush_hypothesis()

                    rest_audio_lengths = rest_audio_lengths - chunk_lengths_batch
                    left_sample = right_sample
                    right_sample = min(right_sample + context_samples.chunk, T)

        try:
            while True:
                try:
                    item = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if item is None:
                    consume_streaming(audio_buf.total, stream_end=True)
                    break

                f32 = _pcm16_to_f32_mono(item)
                if self.sample_rate != audio_sample_rate:
                    f32 = _resample_linear(f32, self.sample_rate, audio_sample_rate)
                if f32.size == 0:
                    continue

                audio_buf.append(f32)
                consume_streaming(audio_buf.total, stream_end=False)

        except Exception as e:
            if self.on_error:
                self.on_error(f"Parakeet streaming error: {e}")
        finally:
            try:
                flush_hypothesis()
            except Exception:
                pass
            self.text_queue.put(None)
