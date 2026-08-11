from PyInstaller.utils.hooks import collect_all

# tkinterdnd2 bundles platform-specific Tcl/Tk native libraries. Collecting all
# package assets keeps native OS drag-and-drop working in the frozen executable.
datas, binaries, hiddenimports = collect_all("tkinterdnd2")
