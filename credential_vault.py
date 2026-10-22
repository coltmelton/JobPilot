"""Windows-user encrypted credentials and ephemeral browser data.

DPAPI keys are managed by Windows, never stored alongside the encrypted files.
The vault stays outside the project/OneDrive folder. There is no plaintext fallback.
"""
import ctypes
import json
import os
import uuid
from pathlib import Path
from ctypes import wintypes

from browser_sessions import session_key

VAULT_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'JobPilot' / 'private'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Encrypted workflow storage currently requires Windows. No plaintext fallback is used.')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('Windows could not unlock this private data for the current user.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def protect(data):
    return _crypt(data)


def unprotect(data):
    return _crypt(data, decrypt=True)


def _path(kind, url=None):
    return VAULT_DIR / (kind + '-' + (session_key(url) if url else 'shared') + '.enc')


def _write(path, value):
    encrypted = protect(json.dumps(value).encode('utf-8'))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_bytes(encrypted)
    temporary.replace(path)


def _read(path):
    return json.loads(unprotect(path.read_bytes()).decode('utf-8')) if path.exists() else None


def save_credentials(email, password, url=None):
    if not email.strip() or not password:
        raise ValueError('Provide both an email and a password.')
    _write(_path('login', url), {'email': email.strip(), 'password': password})


def allow_shared(url):
    if not _path('login').exists():
        raise ValueError('Save your shared application login first.')
    _write(_path('approval', url), {'allowed': True})


def get_credentials(url):
    own = _read(_path('login', url))
    if own:
        return own
    if _read(_path('approval', url)):
        return _read(_path('login'))
    return None


def credential_status(url=None):
    if url is None:
        return _path('login').exists()
    return _path('login', url).exists() or (_path('approval', url).exists() and _path('login').exists())


def forget_credentials(url=None):
    _path('login', url).unlink(missing_ok=True)
    if url:
        _path('approval', url).unlink(missing_ok=True)


def load_browser_state(url):
    state = _read(_path('session', url))
    if state is not None:
        return state
    # Read legacy saved sessions without exposing them in the UI or logs.
    from browser_sessions import state_path
    legacy = state_path(url)
    return json.loads(legacy.read_text(encoding='utf-8')) if legacy.exists() else None


def save_browser_state(context, url):
    _write(_path('session', url), context.storage_state(indexed_db=True))


def browser_state_exists(url):
    return _path('session',url).exists()


def forget_browser_state(url):
    _path('session',url).unlink(missing_ok=True)
