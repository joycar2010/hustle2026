@echo off
cd d:\git\boolean\miniprogram
for /r %%f in (*.ts) do (
    ren "%%f" "%%~nf.js"
)
echo Done!
