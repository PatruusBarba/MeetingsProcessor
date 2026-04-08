# BrainstormAssistant — Product Specification

## 1. Overview

**BrainstormAssistant** is a voice-driven desktop brainstorming assistant for Windows.
It helps the user formulate raw ideas into actionable plans through conversational AI,
critical analysis, structured document generation, and visual output.

The user speaks an idea, the assistant helps refine it through critical dialogue,
then produces artifacts: evaluation reports, spec documents, and business plans.

---

## 2. Target Platform & Architecture

| Layer | Technology |
|-------|-----------|
| Desktop App | WPF (.NET 8, Windows 10+) |
| LLM Backend | OpenAI-compatible API (OpenRouter, OpenAI, local via LM Studio, custom endpoint) |
| TTS | Windows System.Speech (built-in synthesizer) |
| STT | NVIDIA Parakeet TDT ONNX (local, ~670 MB int8 quantized) |
| Persistence | JSON files in `%AppData%\BrainstormAssistant` |
| Future: Companion | .NET MAUI Android app (local network) |

---

## 3. Feature Specification

### Phase 1 — Core Voice Chat

| # | Feature | Description | Status |
|---|---------|-------------|--------|
| 1.1 | **Text Chat** | Multi-turn conversational interface with message history | ✅ Done |
| 1.2 | **LLM Integration** | OpenAI-compatible chat completions (OpenRouter, OpenAI, custom endpoints) | ✅ Done |
| 1.3 | **System Prompt** | Assistant is a critical-thinking brainstorming partner; responds in user's language | ✅ Done |
| 1.4 | **TTS (Text-to-Speech)** | Windows System.Speech; configurable voice, rate, volume; async speak/stop | ✅ Done |
| 1.5 | **STT (Speech-to-Text)** | Local NVIDIA Parakeet ONNX model; silence detection; continuous listening; partial results | ✅ Done |
| 1.6 | **STT Model Download** | Auto-download Parakeet int8 models from HuggingFace (~670 MB) | ✅ Done |
| 1.7 | **Configuration UI** | Settings window: provider, API key, model, temperature, max tokens, TTS/STT toggles | ✅ Done |

### Phase 2 — Analysis & Document Generation

| # | Feature | Description | Status |
|---|---------|-------------|--------|
| 2.1 | **Critical Idea Evaluation** | Structured JSON output: viability score (0–10), risks, strengths, weaknesses, monetization options, target audience, estimated resources/cost/timeline | ✅ Done |
| 2.2 | **Business Plan Generation** | Comprehensive markdown: executive summary, market analysis, financials, launch strategy; with realistic critical analysis (not overly optimistic) | ✅ Done |
| 2.3 | **Spec/PRD Generation** | Technical specification document: product overview, features, components, architecture | ✅ Done |
| 2.4 | **Session Summary** | Condensed summary of the brainstorming discussion | ✅ Done |
| 2.5 | **Honest Critical Feedback** | The assistant must NOT flatter; it should genuinely analyze viability, highlight risks and flaws, and challenge weak assumptions | ✅ Done (via system prompt) |

### Phase 3 — Visualization Board

| # | Feature | Description | Status |
|---|---------|-------------|--------|
| 3.1 | **Markdown Board** | Render formatted text from LLM responses; support headings, lists, code blocks | ✅ Done |
| 3.2 | **HTML Board** | Render arbitrary HTML/CSS/JS from LLM responses for richer visualization | ✅ Done |
| 3.3 | **Dual-Tab Board** | Two tabs (Markdown & HTML) in a collapsible side panel; AI or user can use either | ✅ Done |
| 3.4 | **Mermaid Diagrams** | Auto-detect ```mermaid``` blocks; render flowcharts, mind maps, sequence diagrams via Mermaid.js CDN | ✅ Done |
| 3.5 | **Board Toggle** | Show/hide the board panel from the toolbar | ✅ Done |

### Phase 4 — Session & Artifact Management

| # | Feature | Description | Status |
|---|---------|-------------|--------|
| 4.1 | **Session CRUD** | Create, save, load, delete brainstorming sessions | ✅ Done |
| 4.2 | **Session List Browser** | Sortable list with timestamps, double-click to load, delete with confirmation | ✅ Done |
| 4.3 | **Per-Session Artifact Folders** | Each session gets its own folder for generated artifacts | ✅ Done |
| 4.4 | **Artifact Save** | Save board content as `.md` or `.html` files into the session folder | ✅ Done |
| 4.5 | **Session Export** | Export entire session (chat history) as Markdown | ✅ Done |
| 4.6 | **Scoped File Access** | Agent reads/writes only files within the current session folder | ✅ Done |

### Phase 5 — In-Session Model Switching

| # | Feature | Description | Status |
|---|---------|-------------|--------|
| 5.1 | **Model Switch via Tool Call** | User asks to switch model in natural language; LLM invokes `switch_model` tool; app executes it and persists the change | ✅ Done |
| 5.2 | **Model Info Query via Tool Call** | User asks what model is active or what's available; LLM invokes `get_model_info` tool to get current model and provider, then answers | ✅ Done |

### Phase 6 — Android Companion App

| # | Feature | Description | Status |
|---|---------|-------------|--------|
| 6.1 | **Companion App** | .NET MAUI Android app scaffold with dark-themed UI; connects to PC over local network | ✅ Done |
| 6.2 | **Push-to-Talk Button** | Single button UI: hold to record, release to send audio to PC | ✅ Done |
| 6.3 | **Audio Streaming** | Recorded voice sent to PC for STT → LLM processing; TTS response audio streamed back and played | ✅ Done |
| 6.4 | **Local Network Discovery** | Manual server address entry with connection test via `/api/status` | ⚠️ Manual only |
| 6.5 | **Bluetooth Headphone Support** | Android manifest includes BLUETOOTH permissions; uses standard AudioRecord API | ⚠️ Permissions only |
| 6.6 | **Voice Activity Detection (VAD)** | Energy-based RMS speech detection with adaptive noise floor, configurable threshold and silence timeout | ✅ Done |
| 6.7 | **Hands-Free Mode** | VAD toggle in UI; automatic speech capture and processing without button press | ✅ Done |
| 6.8 | **HTML Board on Phone** | BoardPage with WebView fetches HTML from `/api/board` endpoint; refresh support | ✅ Done |
| 6.9 | **PC-Side Server** | HTTP server (port 5225) embedded in WPF app; endpoints: `GET /api/status`, `POST /api/chat`, `POST /api/audio`; Server toggle in toolbar; TTS audio as base64 WAV | ✅ Done |

---

## 4. Idea-to-Output Pipeline (Workflow)

The core workflow the application enables:

```
1. USER speaks a raw idea
       ↓
2. ASSISTANT helps structure & discuss the idea
   - What is the product?
   - Who is the target audience?
   - How does it work?
   - What components/tech are needed?
   - How much will it cost? How long to build?
       ↓
3. ASSISTANT provides critical evaluation
   - Viability score (0–10)
   - Risks, weaknesses, strengths
   - Monetization potential
   - Honest, not flattering
       ↓
4. USER and ASSISTANT iterate & refine
   - Address weaknesses
   - Adjust scope
   - Re-evaluate
       ↓
5. Generate SPEC / PRD document
   - Product overview, features, architecture
   - Saved as artifact (.md)
       ↓
6. Generate BUSINESS PLAN
   - Market analysis, financials, launch strategy
   - Saved as artifact (.md)
       ↓
7. Artifacts are stored per-session for later use
   (e.g., feed into Cursor/Copilot for implementation)
```

---

## 5. UI Layout (Desktop)

```
┌─────────────────────────────────────────────────────────────────┐
│  [New] [Load] [Save] [Export]  |  [Summary] [Evaluate]         │
│  [Biz Plan] [Spec]            |  [Settings]                   │
├──────────────────────────────────┬──────────────────────────────┤
│                                  │                              │
│         CHAT PANEL               │       BOARD PANEL            │
│                                  │    ┌──────┬───────┐          │
│  ┌──────────────────────┐        │    │  MD  │ HTML  │          │
│  │ 🤖 Assistant message │        │    ├──────┴───────┤          │
│  └──────────────────────┘        │    │              │          │
│       ┌──────────────────────┐   │    │  Rendered    │          │
│       │ 👤 User message     │   │    │  Content     │          │
│       └──────────────────────┘   │    │              │          │
│                                  │    │  (Markdown   │          │
│  ┌──────────────────────┐        │    │   or HTML    │          │
│  │ 🤖 Assistant message │        │    │   + Mermaid) │          │
│  └──────────────────────┘        │    │              │          │
│                                  │    └──────────────┘          │
│                                  │                              │
├──────────────────────────────────┴──────────────────────────────┤
│  [🎙️ Mic] [  Type a message...                ] [Send] [🔊] [📋]│
│  Partial: "I was thinking about..."                             │
├─────────────────────────────────────────────────────────────────┤
│  Status: Ready                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Model

```
ChatMessage
├── Role         : string ("user" | "assistant" | "system")
├── Content      : string
└── Timestamp    : long (unix ms)

Session
├── Id           : string (GUID)
├── Title        : string
├── CreatedAt    : DateTime
├── UpdatedAt    : DateTime
├── Messages     : List<ChatMessage>
└── Summary      : string

IdeaEvaluation
├── IdeaSummary          : string
├── TargetAudience       : string
├── Components           : List<string>
├── EstimatedResources   : string
├── Cost                 : string
├── Timeline             : string
├── MonetizationOptions  : List<string>
├── ViabilityScore       : int (0–10)
├── Risks                : List<string>
├── Strengths            : List<string>
├── Weaknesses           : List<string>
└── Recommendation       : string

AppConfig
├── Provider      : string ("openrouter" | "openai" | "custom")
├── ApiKey         : string
├── Model          : string
├── BaseUrl        : string (for custom provider)
├── Temperature    : double
├── MaxTokens      : int
├── TtsEnabled     : bool
├── TtsVoice       : string
├── TtsRate        : int
├── TtsVolume      : int
└── SttEnabled     : bool
```

---

## 7. Persistence

| Data | Location | Format |
|------|----------|--------|
| Sessions | `%AppData%\BrainstormAssistant\sessions\{id}.json` | JSON |
| Artifacts | `%AppData%\BrainstormAssistant\sessions\{id}\artifacts\` | .md, .html |
| Config | `%AppData%\BrainstormAssistant\config.json` | JSON |
| STT Models | `%AppData%\BrainstormAssistant\models\` | ONNX |

---

## 8. Non-Functional Requirements

| Requirement | Detail |
|-------------|--------|
| **Offline STT** | Speech recognition works fully offline (Parakeet ONNX) |
| **Offline TTS** | Text-to-speech works fully offline (Windows System.Speech) |
| **LLM requires network** | Unless using a local model (LM Studio, etc.) |
| **Dark Theme** | Entire UI uses dark color scheme |
| **Language** | Assistant responds in the user's language (multilingual) |
| **MVVM Pattern** | WPF app follows Model-View-ViewModel architecture |
| **Test Coverage** | 11 xUnit test classes with Moq; covers all services and models |

---

## 9. Implementation Status Summary

| Phase | Name | Status |
|-------|------|--------|
| Phase 1 | Core Voice Chat | ✅ **Complete** |
| Phase 2 | Analysis & Document Generation | ✅ **Complete** |
| Phase 3 | Visualization Board | ✅ **Complete** |
| Phase 4 | Session & Artifact Management | ✅ **Complete** |
| Phase 5 | In-Session Model Switching | ✅ **Complete** |
| Phase 6 | Android Companion App | ✅ **Complete** |

**All phases (1–6) are fully implemented.**
The desktop app is production-ready. The Android companion app is scaffolded as a .NET MAUI project
and requires `dotnet workload install maui` + Android SDK to build.

---

## 10. Glossary

| Term | Meaning |
|------|---------|
| **Board** | Side panel that renders Markdown or HTML output from the assistant |
| **Artifact** | A generated file (.md or .html) saved to the session folder |
| **Evaluation** | Structured critical analysis of an idea (JSON with viability score) |
| **Companion App** | Future Android app that connects to the desktop app for hands-free use |
| **VAD** | Voice Activity Detection — auto-detect when the user starts/stops speaking |
| **Parakeet** | NVIDIA's speech recognition model (ONNX format, runs locally) |
| **OpenRouter** | LLM API aggregator that provides access to many models via OpenAI-compatible API |
