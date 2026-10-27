# Сборка из рабочего дерева репозитория: abuild -r в этом каталоге
pkgname=titan-keyboard
pkgver=0.1.0
pkgrel=0
pkgdesc="Клавиатура Titan: модификаторы, слои, раскладки и IME (совместимо с Plektra)"
url="https://github.com/"
arch="noarch"
license="GPL-3.0-or-later"
depends="python3 py3-evdev py3-gobject3 py3-pywayland gtk4-layer-shell wl-clipboard"
options="!check"

package() {
	install -d "$pkgdir"/usr/lib/titan "$pkgdir"/usr/share/titan-keyboard
	cp -r "$startdir"/titan_keyboard "$pkgdir"/usr/lib/titan/
	cp -r "$startdir"/data "$pkgdir"/usr/share/titan-keyboard/
}
