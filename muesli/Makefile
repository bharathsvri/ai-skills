.PHONY: app run debug test icon install clean

app:
	@bash Scripts/build-app.sh release

run: app
	@open build/Muesli.app

debug:
	@swift build

test:
	@swift test

icon:
	@swift Scripts/make-icon.swift
	@echo "Wrote Support/AppIcon.icns"

install: app
	@mkdir -p ~/Applications
	@rm -rf ~/Applications/Muesli.app
	@cp -R build/Muesli.app ~/Applications/Muesli.app
	@echo "Installed to ~/Applications/Muesli.app"

clean:
	@rm -rf .build build
