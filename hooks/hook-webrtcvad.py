from PyInstaller.utils.hooks import copy_metadata

# Override the default hook: metadata is registered as 'webrtcvad-wheels'
datas = copy_metadata('webrtcvad-wheels')
