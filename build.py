#!/usr/bin/env python3
"""
Build script for CBCM Vimeo Downloader
Generates a single-file executable using PyInstaller
Updates app.py version dynamically based on build version
"""

import subprocess
import sys
import os
import re
import shutil
from pathlib import Path


# ---------------------------------------------------------------------------
# Command execution utilities
# ---------------------------------------------------------------------------

def run_command(cmd, description):
    """Run a shell command and handle errors."""
    print(f"\n{description}...")
    try:
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {description} failed with exit code {e.returncode}")
        return False


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

def update_app_version(version):
    """Update the APP_VERSION variable in app.py"""
    app_file = Path("app.py")
    content = app_file.read_text(encoding="utf-8")
    
    pattern = r'APP_VERSION = "[^"]*"'
    replacement = f'APP_VERSION = "{version}"'
    
    updated_content = re.sub(pattern, replacement, content)
    
    if updated_content != content:
        app_file.write_text(updated_content, encoding="utf-8")
        print(f"[OK] Updated APP_VERSION to {version}")
        return True
    else:
        print("[!] Could not find APP_VERSION in app.py to update")
        return False


# ---------------------------------------------------------------------------
# Artifact cleanup
# ---------------------------------------------------------------------------

def cleanup_build_artifacts():
    """Remove build directory and spec file, keeping only dist folder"""
    artifacts = [Path("build"), Path("build.spec")]
    
    for artifact in artifacts:
        try:
            if artifact.is_dir():
                shutil.rmtree(artifact)
                print(f"[OK] Removed {artifact}/")
            elif artifact.is_file():
                artifact.unlink()
                print(f"[OK] Removed {artifact}")
        except Exception as e:
            print(f"[!] Could not remove {artifact}: {e}")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_build_arguments():
    """Parse command-line arguments and return (version, onedir_mode)."""
    version = "0.0.1"
    onedir_mode = "--onedir" in sys.argv
    
    if len(sys.argv) > 1:
        version = sys.argv[1]
    
    return version, onedir_mode


def print_build_header(version):
    """Print the build script header."""
    print("\n" + "=" * 50)
    print("CBCM Vimeo Downloader - Build Script")
    print(f"Version: {version}")
    print("=" * 50)


# ---------------------------------------------------------------------------
# Pre-build checks
# ---------------------------------------------------------------------------

def check_app_file_exists():
    """Verify app.py exists in the current directory."""
    if not Path("app.py").exists():
        print("\nERROR: app.py not found in current directory!")
        return False
    return True


def ensure_pyinstaller_installed():
    """Check and install PyInstaller if needed."""
    try:
        import PyInstaller
        return True
    except ImportError:
        print("\nPyInstaller not found. Installing...")
        return run_command(
            [sys.executable, "-m", "pip", "install", "pyinstaller"], 
            "Installing PyInstaller"
        )


# ---------------------------------------------------------------------------
# Build command construction
# ---------------------------------------------------------------------------

def get_exe_name(version):
    """Generate the executable name from the version string."""
    return f"CBCMVimeoDownloader-v-{version.replace('.', '-')}"


def build_pyinstaller_args(exe_name, onedir_mode):
    """Build the base PyInstaller command arguments."""
    return [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir" if onedir_mode else "--onefile",
        "--windowed",
        "--name", exe_name,
        "--distpath", "./dist",
        "--workpath", "./build",
        "--specpath", "./build",
        "--collect-all=encodings",
        "--collect-all=tkinter",
        "--hidden-import=tkinter",
        "--hidden-import=threading",
        "--hidden-import=json",
    ]


def add_icon_to_build(build_cmd):
    """Add icon to build command if appicon.ico exists."""
    icon_path = Path("appicon.ico")
    if icon_path.exists():
        icon_abs_path = icon_path.absolute()
        build_cmd.append(f"--icon={icon_abs_path}")
        print(f"[OK] Using icon: appicon.ico")
        return True
    return False


def finalize_build_command(build_cmd):
    """Add the app.py argument and return the complete command."""
    build_cmd.append("app.py")
    return build_cmd


# ---------------------------------------------------------------------------
# Build execution and output
# ---------------------------------------------------------------------------

def execute_build(build_cmd):
    """Execute the PyInstaller build command."""
    return run_command(build_cmd, "Building executable")


def get_exe_path(exe_name, onedir_mode):
    """Return the path to the generated executable."""
    if onedir_mode:
        return Path(f"dist/{exe_name}/{exe_name}.exe")
    return Path(f"dist/{exe_name}.exe")


def print_success_message(exe_name, onedir_mode):
    """Print the build success message with output location."""
    print("\n" + "=" * 50)
    print("Build completed successfully!")
    print("=" * 50)
    
    exe_path = get_exe_path(exe_name, onedir_mode)
    
    if onedir_mode:
        folder_path = Path(f"dist/{exe_name}").absolute()
        print(f"\nExecutable location (folder mode):")
        print(f"  {folder_path}")
        print(f"\nTo run: dist\\{exe_name}\\{exe_name}.exe")
    else:
        print(f"\nExecutable location:")
        print(f"  {exe_path.absolute()}")
        if exe_path.exists():
            file_size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\nFile size: {file_size_mb:.1f} MB")


def open_dist_folder(exe_name, onedir_mode):
    """Prompt user to open the dist folder."""
    try:
        response = input("\nOpen dist folder? (y/n): ").strip().lower()
        if response != 'y':
            return
            
        folder = (Path(f"dist/{exe_name}").absolute() 
                  if onedir_mode 
                  else Path("dist").absolute())
        
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)])
        else:
            subprocess.run(["xdg-open", str(folder)])
    except Exception as e:
        print(f"Could not open folder: {e}")


# ---------------------------------------------------------------------------
# Main build pipeline
# ---------------------------------------------------------------------------

def main():
    """Execute the complete build pipeline."""
    # Parse arguments
    version, onedir_mode = parse_build_arguments()
    print_build_header(version)
    
    # Pre-build validation
    if not check_app_file_exists():
        sys.exit(1)
    
    # Update version in source code
    if not update_app_version(version):
        print("\nWARNING: Could not update app.py version (but continuing)")
    
    # Ensure PyInstaller is available
    if not ensure_pyinstaller_installed():
        sys.exit(1)
    
    # Build PyInstaller command
    exe_name = get_exe_name(version)
    build_cmd = build_pyinstaller_args(exe_name, onedir_mode)
    add_icon_to_build(build_cmd)
    build_cmd = finalize_build_command(build_cmd)
    
    # Execute build
    if not execute_build(build_cmd):
        sys.exit(1)
    
    # Post-build cleanup and output
    print("\nCleaning up build artifacts...")
    cleanup_build_artifacts()
    
    print_success_message(exe_name, onedir_mode)
    open_dist_folder(exe_name, onedir_mode)


if __name__ == "__main__":
    main()
