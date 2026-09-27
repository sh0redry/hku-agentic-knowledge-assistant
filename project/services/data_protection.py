from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class DataProtectionUnavailable(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsUserDataProtector:
    """Protect small local secrets with the current Windows user's DPAPI key."""

    _DESCRIPTION = "HKU AGENTS Library shadow-only authorization"
    _UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise DataProtectionUnavailable(
                "F3 shadow rules require Windows user-scope data protection."
            )
        self._crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p
        probe = b"HKU AGENTS F3 DPAPI self-check"
        if self.unprotect(self.protect(probe)) != probe:
            raise DataProtectionUnavailable(
                "Windows current-user data protection did not pass its self-check."
            )

    @staticmethod
    def _input_blob(value: bytes):
        storage = ctypes.create_string_buffer(value)
        blob = _DataBlob(
            len(value), ctypes.cast(storage, ctypes.POINTER(ctypes.c_byte))
        )
        return storage, blob

    def _release(self, blob: _DataBlob) -> None:
        if blob.pbData:
            self._kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))

    def protect(self, value: bytes) -> bytes:
        _storage, source = self._input_blob(value)
        output = _DataBlob()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source), self._DESCRIPTION, None, None, None,
            self._UI_FORBIDDEN, ctypes.byref(output),
        ):
            raise DataProtectionUnavailable(
                f"Windows could not protect F3 shadow data (error {ctypes.get_last_error()})."
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._release(output)

    def unprotect(self, value: bytes) -> bytes:
        _storage, source = self._input_blob(value)
        output = _DataBlob()
        description = wintypes.LPWSTR()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source), ctypes.byref(description), None, None, None,
            self._UI_FORBIDDEN, ctypes.byref(output),
        ):
            raise DataProtectionUnavailable(
                f"Windows could not open F3 shadow data (error {ctypes.get_last_error()})."
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._release(output)
            if description:
                self._kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))
