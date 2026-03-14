# Build Instructions

This directory contains a cross-platform build script to generate the executable for the CBCM Vimeo Downloader application.

## Prerequisites

Make sure you have the required dependencies installed:

```bash
pip install -r requirements.txt
```

For building executables, install the development dependencies:

```bash
pip install -r requirements-dev.txt
```

The build script will automatically install PyInstaller if it's not already available.

## Building the Executable

Run the build script from command line:

```bash
python build.py
```

Or:

```bash
python3 build.py
```

### Specifying a Version

You can specify a custom version number as an argument:

```bash
python build.py 1.0.2
```

This will:
- Update the `APP_VERSION` variable in `app.py` to `1.0.2`
- Generate the executable: `CBCMVimeoDownloader-v-1-0-2.exe`
- The GUI will display the updated version in the title bar

If no version is provided, it defaults to `0.0.1` (for local testing).

### Build Modes

#### Single-File Mode (Default)
```bash
python build.py 1.0.2
```

Creates a single executable file: `dist/CBCMVimeoDownloader-v-1-0-2.exe`

**Advantages:**
- Easy distribution (just one file)
- Simpler to share and deploy

**Note:** May occasionally show a harmless warning on Windows startup about Python encoding (does not affect functionality).

#### Folder Mode (Recommended for Windows)
```bash
python build.py 1.0.2 --onedir
```

Creates a folder with the executable and dependencies: `dist/CBCMVimeoDownloader-v-1-0-2/CBCMVimeoDownloader-v-1-0-2.exe`

**Advantages:**
- Avoids startup warnings/errors
- Faster startup time
- Better compatibility with Windows antivirus software

**Use this mode if you experience any startup errors.**

## Build Output

The generated executable will be located at:

```
dist/CBCMVimeoDownloader-v-1-0-1.exe
```

## Build Process

The build script handles the following automatically:

1. **Version Management** - Updates `APP_VERSION` in app.py to match the specified version
2. **Build Mode Selection** - Creates either a single-file EXE (default) or a folder with dependencies (`--onedir`)
3. **PyInstaller Configuration** - Bundles the application with:
   - GUI mode (`--windowed` flag) - no console window
   - Proper module collection - ensures all required dependencies are included
4. **Cleanup** - Automatically removes temporary build artifacts (`build/` folder and `.spec` file)
5. **Consistency** - Ensures the executable filename, source code version, and GUI display all match

## Build Artifacts

### Single-File Mode (Default)
After a successful build, only the executable remains:
- `dist/CBCMVimeoDownloader-v-X-X-X.exe` - The final executable

### Folder Mode (--onedir)
After a successful build, a folder with the executable and dependencies:
- `dist/CBCMVimeoDownloader-v-X-X-X/CBCMVimeoDownloader-v-X-X-X.exe` - The executable
- `dist/CBCMVimeoDownloader-v-X-X-X/` - All required dependencies

All temporary build files are automatically cleaned up in both modes:
- `build/` directory is removed
- `build.spec` file is removed

This keeps your project directory clean.

## Version Management

The application uses a global `APP_VERSION` variable defined in `app.py`:

```python
APP_VERSION = "0.0.1"
```

The build script automatically updates this variable when you specify a version argument:

```bash
python build.py 1.2.3
```

This ensures consistency between:
- The executable filename: `CBCMVimeoDownloader-v-1-2-3.exe`
- The GUI version display in the title bar: `v1.2.3`

## Troubleshooting

### "Failed to import encodings module" at startup

This is a known PyInstaller issue on Windows with Tkinter applications.

**Solution:** Use folder mode when building:

```bash
python build.py 1.0.2 --onedir
```

The folder-based output avoids this startup issue entirely. This is the recommended approach for Windows users.

**Alternative:** If you must use single-file mode, the error is harmless and doesn't impact functionality. The application will run normally after the warning.

## Customizing the Build

To modify the build configuration, edit either `build.bat` or `build.py` and adjust the arguments passed to PyInstaller. Common options:

- `--name` - Change the executable name
- `--icon` - Add a custom icon (requires `.ico` file)
- `--add-data` - Include additional files
- `--hidden-import` - Specify hidden imports if needed

For more PyInstaller options, see: https://pyinstaller.org/en/stable/
