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


def run_command(cmd, description):
    """Run a shell command and handle errors."""
    print(f"\n{description}...")
    try:
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {description} failed with exit code {e.returncode}")
        return False


def update_app_version(version):
    """Update the APP_VERSION variable in app.py"""
    app_file = Path("app.py")
    content = app_file.read_text(encoding="utf-8")
    
    # Replace the APP_VERSION variable
    pattern = r'APP_VERSION = "[^"]*"'
    replacement = f'APP_VERSION = "{version}"'
    
    updated_content = re.sub(pattern, replacement, content)
    
    if updated_content != content:
        app_file.write_text(updated_content, encoding="utf-8")
        print(f"✓ Updated APP_VERSION to {version}")
        return True
    else:
        print("⚠ Could not find APP_VERSION in app.py to update")
        return False


def cleanup_build_artifacts():
    """Remove build directory and spec file, keeping only dist folder"""
    artifacts = [
        Path("build"),
        Path("build.spec")
    ]
    
    for artifact in artifacts:
        try:
            if artifact.is_dir():
                shutil.rmtree(artifact)
                print(f"✓ Removed {artifact}/")
            elif artifact.is_file():
                artifact.unlink()
                print(f"✓ Removed {artifact}")
        except Exception as e:
            print(f"⚠ Could not remove {artifact}: {e}")


def main():
    # Parse version argument
    version = "0.0.1"  # Default version for local testing
    onedir_mode = False
    
    if len(sys.argv) > 1:
        version = sys.argv[1]
    
    # Check for --onedir flag
    if "--onedir" in sys.argv:
        onedir_mode = True
    
    print("\n" + "=" * 50)
    print("CBCM Vimeo Downloader - Build Script")
    print(f"Version: {version}")
    print("=" * 50)
    
    # Check if app.py exists
    if not Path("app.py").exists():
        print("\nERROR: app.py not found in current directory!")
        sys.exit(1)
    
    # Update version in app.py
    if not update_app_version(version):
        print("\nWARNING: Could not update app.py version (but continuing with build)")
    
    # Check and install PyInstaller if needed
    try:
        import PyInstaller
    except ImportError:
        print("\nPyInstaller not found. Installing...")
        if not run_command([sys.executable, "-m", "pip", "install", "pyinstaller"], 
                          "Installing PyInstaller"):
            sys.exit(1)
    
    # Build the executable with dynamic version in the name
    exe_name = f"CBCMVimeoDownloader-v-{version.replace('.', '-')}"
    build_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile" if not onedir_mode else "--onedir",
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
        "app.py"
    ]
    
    if not run_command(build_cmd, "Building executable"):
        sys.exit(1)
    
    # Clean up build artifacts
    print("\nCleaning up build artifacts...")
    cleanup_build_artifacts()
    
    # Print success message
    if onedir_mode:
        exe_path = Path(f"dist/{exe_name}/{exe_name}.exe")
        print("\n" + "=" * 50)
        print("Build completed successfully!")
        print("=" * 50)
        print(f"\nExecutable location (folder mode):")
        print(f"  {Path(f'dist/{exe_name}').absolute()}")
        print(f"\nTo run: dist\\{exe_name}\\{exe_name}.exe")
    else:
        exe_path = Path(f"dist/{exe_name}.exe")
        print("\n" + "=" * 50)
        print("Build completed successfully!")
        print("=" * 50)
        print(f"\nExecutable location:")
        print(f"  {exe_path.absolute()}")
        if exe_path.exists():
            print(f"\nFile size: {exe_path.stat().st_size / (1024*1024):.1f} MB")
    
    # Ask to open folder
    try:
        response = input("\nOpen dist folder? (y/n): ").strip().lower()
        if response == 'y':
            folder = Path(f"dist/{exe_name}").absolute() if onedir_mode else Path("dist").absolute()
            if sys.platform == "win32":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(folder)])
            else:
                subprocess.run(["xdg-open", str(folder)])
    except Exception as e:
        print(f"Could not open folder: {e}")


if __name__ == "__main__":
    main()
