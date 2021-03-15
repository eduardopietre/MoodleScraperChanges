# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(['MoodleScraperChanges.py'],
             pathex=['D:\\Development\\Python\\MoodleScraperChanges'],
             binaries=[],
             datas=[],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='MoodleScraperChanges',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='MoodleScraperChanges')


import os
import shutil

dist_folder = "dist/MoodleScraperChanges"
# adapted from https://stackoverflow.com/questions/60057003/copying-license-dependencies-for-pyinstaller
matches = ["LICENSE.txt", "METADATA", "PKG-INFO"]
for root, _, files in os.walk("venv\Lib\site-packages"):
    for file in files:
        if file in matches:
            src = f"{root}/{file}"
            dest = f"{dist_folder}/licenses/{os.path.basename(root)}"
            print(f"\tLicense file: {src}")

            os.makedirs(dest, exist_ok=True)
            shutil.copy(src, f"{dest}/{file}")

shutil.copy("config.ini", f"{dist_folder}/config.ini")
shutil.copy("Courses.txt", f"{dist_folder}/Courses.txt")
shutil.copy("MoodleSession.txt", f"{dist_folder}/MoodleSession.txt")
