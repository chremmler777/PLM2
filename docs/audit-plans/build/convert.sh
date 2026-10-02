#!/bin/bash
# Word -> PDF via Microsoft Word (Windows side), fields updated. Usage: ./convert.sh
set -e
cd "$(dirname "$0")/.."
LD=$(cat build/.convdir); WD=$(wslpath -w "$LD")
rm -f "${LD:?}"/*.docx "${LD:?}"/*.pdf
cp ./*.docx "$LD/"
cat > "$LD/conv.ps1" <<PS
\$w = New-Object -ComObject Word.Application
\$w.Visible = \$false; \$w.DisplayAlerts = 0
Get-ChildItem -Path "$WD" -Filter *.docx | ForEach-Object {
  \$d = \$w.Documents.Open(\$_.FullName, \$false, \$false)
  \$d.Fields.Update() | Out-Null
  foreach (\$s in \$d.Sections) { foreach (\$h in \$s.Headers) { \$h.Range.Fields.Update() | Out-Null } }
  \$d.SaveAs([ref]([System.IO.Path]::ChangeExtension(\$_.FullName, ".pdf")), [ref]17)
  \$d.Close([ref]0)
}
\$w.Quit()
PS
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$WD\\conv.ps1"
mkdir -p pdf; cp "$LD"/*.pdf pdf/
for f in pdf/*.pdf; do echo "$f $(pdfinfo "$f" | awk '/Pages/{print $2}') pages"; done
