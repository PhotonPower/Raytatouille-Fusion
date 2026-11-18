# Benutzerhandbuch (LaTeX)

`handbuch.pdf` ist das Benutzerhandbuch von Raytatouille Fusion (deutsch), `handbuch.tex` seine
Quelle mit den Kapiteln in `kapitel/` und den Anhängen in `anhang/`; gemeinsame Pakete und Makros
stehen in `preamble.tex`.

Übersetzen (TeX Live 2024 oder neuer, LuaLaTeX):

```sh
cd docs/manual
make            # latexmk -lualatex, Ergebnis: handbuch.pdf
```

Bilder kommen aus `docs/images/` und `docs/manual/bilder/`.
