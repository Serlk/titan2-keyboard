# Сборка из рабочего дерева: abuild -r в корне репозитория
pkgname=titan-keyboard
pkgver=0.1.0
pkgrel=0
pkgdesc="Клавиатура Titan: модификаторы, слои, раскладки и IME (совместимо с Plektra)"
url="https://github.com/Serlk/titan2-keyboard"
arch="noarch"
license="GPL-3.0-or-later"
makedepends="gettext"
depends="python3 py3-evdev py3-gobject3 py3-cairo py3-pywayland gtk4.0 libadwaita gtk4-layer-shell wl-clipboard"
options="!check"

package() {
	install -d "$pkgdir"/usr/lib/titan "$pkgdir"/usr/share/titan-keyboard
	cp -r "$startdir"/titan_keyboard "$pkgdir"/usr/lib/titan/
	for po in "$startdir"/po/*.po; do
		lang=$(basename "$po" .po)
		install -d "$pkgdir"/usr/share/locale/$lang/LC_MESSAGES
		msgfmt -o "$pkgdir"/usr/share/locale/$lang/LC_MESSAGES/titan-keyboard.mo "$po"
	done
	cp -r "$startdir"/data "$pkgdir"/usr/share/titan-keyboard/
	install -Dm644 "$startdir"/data/share/applications/org.titan.KeyboardSettings.desktop \
		"$pkgdir"/usr/share/applications/org.titan.KeyboardSettings.desktop
	sed -i 's|^Exec=.*|Exec=titan-keyboard-settings|' "$pkgdir"/usr/share/applications/org.titan.KeyboardSettings.desktop
	install -Dm755 /dev/stdin "$pkgdir"/usr/bin/titan-keyboard <<-EOF2
		#!/bin/sh
		LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so PYTHONPATH=/usr/lib/titan exec python3 -m titan_keyboard.daemon "\$@"
	EOF2
	install -Dm755 /dev/stdin "$pkgdir"/usr/bin/titan-keyboard-settings <<-EOF2
		#!/bin/sh
		PYTHONPATH=/usr/lib/titan exec python3 -m titan_keyboard.settings "\$@"
	EOF2
}
