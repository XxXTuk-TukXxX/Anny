import argparse
import ctypes
import os
import shutil
import sys
from pathlib import Path
from getpass import getpass


def is_windows() -> bool:
    return os.name == "nt"


def program_files_root() -> Path:
    # Prefer 64-bit Program Files when available
    path = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\\Program Files"
    return Path(path)


def create_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def copy_fonts(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Fonts source not found: {src}")
    # Python 3.8+: dirs_exist_ok
    shutil.copytree(src, dst, dirs_exist_ok=True)


def tessesaract_download(argv: list[str]) -> int:
    """Proxy to tesseract_install.tessesaract_download.

    This mirrors the function in tesseract_install.py so callers can
    access it from this module as well. It simply dispatches to the
    implementation in tesseract_install.
    """
    try:
        from tesseract_install import tessesaract_download as _impl  # type: ignore
    except Exception as e:
        print("Failed to import tessesaract_download from tesseract_install:", e)
        return 1
    return _impl(argv)


def resource_path(relative: str) -> Path:
    """Return path to a resource that may be bundled with PyInstaller.

    If running as a PyInstaller onefile app, resources are extracted to
    a temporary folder available via sys._MEIPASS. Otherwise, fall back
    to the directory containing this script.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).parent / relative


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create C:/Program Files/Anny and add a fonts folder.")
    p.add_argument(
        "--fonts-src",
        help="Path to a local fonts directory to copy into Program Files/Anny/fonts. If omitted, uses a './fonts' folder next to this script if present.",
        default=None,
    )
    p.add_argument(
        "--exe-src",
        help="Path to 'Anny.exe' to copy into Program Files/Anny. If omitted, will try to use a bundled 'Anny.exe' if present.",
        default=None,
    )
    p.add_argument(
        "--exe-name",
        help="Destination EXE file name under Program Files/Anny (default: Anny.exe).",
        default="Anny.exe",
    )
    p.add_argument(
        "--google-api-key",
        help="Provide Gemini API key non-interactively; sets GOOGLE_API_KEY in your user environment.",
        default=None,
    )
    p.add_argument(
        "--no-gemini-prompt",
        action="store_true",
        help="Do not prompt for GOOGLE_API_KEY in the console.",
    )
    p.add_argument(
        "--no-copy",
        action="store_true",
        help="Only create the folders; do not copy any fonts.",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    if not is_windows():
        print("This script is intended for Windows only.")
        return 2

    args = parse_args(argv)

    base = program_files_root()
    anny_dir = base / "Anny"
    fonts_dir = anny_dir / "fonts"

    try:
        create_directory(anny_dir)
        create_directory(fonts_dir)
    except PermissionError:
        print(
            "Permission denied creating folders under Program Files. "
            "Please run this script as Administrator."
        )
        return 1

    print(f"Created or verified folder: {anny_dir}")
    print(f"Created or verified folder: {fonts_dir}")

    # Copy Anny.exe (from provided path or bundled resource)
    exe_dst = anny_dir / args.exe_name
    exe_src = Path(args.exe_src) if args.exe_src else resource_path(args.exe_name)
    if exe_src.exists() and exe_src.is_file():
        try:
            shutil.copy2(exe_src, exe_dst)
            print(f"Copied EXE to '{exe_dst}'.")
        except PermissionError:
            print(
                "Permission denied copying Anny.exe into Program Files. "
                "Please run this script as Administrator."
            )
            return 1
        except Exception as e:
            print(f"Failed to copy EXE: {e}")
            return 1
    else:
        if args.exe_src:
            print(f"EXE source not found: '{exe_src}'. Skipping EXE copy.")
        else:
            print(
                "No bundled 'Anny.exe' found and no --exe-src provided. "
                "Skipping EXE copy."
            )

    if not args.no_copy:
        # Determine source: explicit, else bundled ./fonts (supports PyInstaller),
        # else ./fonts next to the script.
        src = Path(args.fonts_src) if args.fonts_src else resource_path("fonts")
        if src.exists() and src.is_dir():
            try:
                copy_fonts(src, fonts_dir)
                print(f"Copied fonts from '{src}' to '{fonts_dir}'.")
            except PermissionError:
                print(
                    "Permission denied copying fonts into Program Files. "
                    "Please run this script as Administrator."
                )
                return 1
            except FileNotFoundError as e:
                print(str(e))
                return 1
        else:
            print(
                f"No fonts copied: source directory not found at '{src}'. "
                "You can provide one with --fonts-src PATH."
            )

    # Set up GOOGLE_API_KEY in the user's environment
    if args.google_api_key or not args.no_gemini_prompt:
        ok = setup_google_api_key(args.google_api_key)
        if not ok:
            # Not fatal for installation; just report
            print("Skipping persistent GOOGLE_API_KEY setup.")

    print("Setup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


# --------- Environment helpers (Gemini API key) ---------
def _broadcast_environment_change() -> None:
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        SendMessageTimeoutW = ctypes.windll.user32.SendMessageTimeoutW
        SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                            ctypes.c_wchar_p("Environment"),
                            SMTO_ABORTIFHUNG, 5000, ctypes.pointer(ctypes.c_ulong()))
    except Exception:
        pass


def _set_user_env_var(name: str, value: str) -> bool:
    # Update current process
    os.environ[name] = value
    # Persist to HKCU\Environment
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as kset:
            # Use REG_SZ; API keys don't need expansion
            winreg.SetValueEx(kset, name, 0, winreg.REG_SZ, value)
        _broadcast_environment_change()
        return True
    except Exception as e:
        print(f"Could not persist {name} in user environment: {e}")
        return False


def _get_existing_user_env_var(name: str) -> str | None:
    # Check current process first
    if name in os.environ and os.environ[name]:
        return os.environ[name]
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as k:
            try:
                val, _ = winreg.QueryValueEx(k, name)
                if val:
                    return str(val)
            except FileNotFoundError:
                return None
    except Exception:
        return None
    return None


def setup_google_api_key(provided_key: str | None = None) -> bool:
    """Prompt the user for GOOGLE_API_KEY and persist it for the current user.

    If provided_key is not None, uses that value non-interactively.
    Returns True if the key is set/persisted; False otherwise.
    """
    name = "GOOGLE_API_KEY"

    # Respect provided value
    key = (provided_key or "").strip() if provided_key else None
    if not key:
        existing = _get_existing_user_env_var(name)
        if existing:
            print("A GOOGLE_API_KEY already exists in your environment.")
            print("Press Enter to keep it, or enter a new key to replace.")
        try:
            # Hide input as it is sensitive
            prompt = "Enter your Gemini API key (GOOGLE_API_KEY): "
            new_val = getpass(prompt)
        except Exception:
            new_val = input("Enter your Gemini API key (GOOGLE_API_KEY): ")
        new_val = new_val.strip()
        if not new_val:
            if existing:
                print("Keeping existing GOOGLE_API_KEY.")
                return True
            else:
                print("No key provided. You can set it later via System Environment Variables.")
                return False
        key = new_val

    # Minimal validation
    if len(key) < 10:
        print("The provided key looks too short; please verify.")

    if _set_user_env_var(name, key):
        print("GOOGLE_API_KEY saved to your user environment.")
        print("Open a new terminal or sign out/in for all apps to pick it up.")
        return True
    return False
