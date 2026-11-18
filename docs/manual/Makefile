# Benutzerhandbuch: make  ->  handbuch.pdf  (LuaLaTeX, latexmk)
handbuch.pdf: handbuch.tex preamble.tex kapitel/*.tex anhang/*.tex
	latexmk -lualatex -interaction=nonstopmode -halt-on-error handbuch.tex
	cp build/handbuch.pdf handbuch.pdf

clean:
	latexmk -C -outdir=build handbuch.tex
	rm -rf build

.PHONY: clean
