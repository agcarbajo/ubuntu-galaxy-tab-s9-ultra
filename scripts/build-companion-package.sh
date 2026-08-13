#!/bin/bash
# Build the architecture-independent Tab Companion Debian package.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
src=$repo/packaging/ubuntu-gts9u-companion
out=${DEB_OUT_DIR:-$base/out/packages}

version=$(awk '/^Version:/ {print $2}' "$src/DEBIAN/control")
staging=$base/build/deb/ubuntu-gts9u-companion
deb=$out/ubuntu-gts9u-companion_${version}_all.deb

rm -rf -- "$staging"
mkdir -p "$staging" "$out"
cp -a "$src/." "$staging/"
find "$staging" -type f -name '*.pyc' -delete
find "$staging" -type d -name '__pycache__' -empty -delete

# Gio resources keep the illustration independent of the current directory.
resource_dir=$staging/usr/share/tab-companion
cat > "$resource_dir/io.github.agcarbajo.TabCompanion.gresource.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<gresources>
  <gresource prefix="/io/github/agcarbajo/TabCompanion/images">
    <file alias="spen-tip-left.svg">spen-tip-left.svg</file>
    <file alias="spen-tip-right.svg">spen-tip-right.svg</file>
  </gresource>
</gresources>
EOF
glib-compile-resources --sourcedir="$resource_dir" \
	--target="$resource_dir/io.github.agcarbajo.TabCompanion.gresource" \
	"$resource_dir/io.github.agcarbajo.TabCompanion.gresource.xml"
rm "$resource_dir/io.github.agcarbajo.TabCompanion.gresource.xml" \
	"$resource_dir/spen-tip-left.svg" \
	"$resource_dir/spen-tip-right.svg"

# Load the resource before Python starts importing the UI.
sed -i '5i\from gi.repository import Gio\nGio.resources_register(Gio.Resource.load("/usr/share/tab-companion/io.github.agcarbajo.TabCompanion.gresource"))' \
	"$staging/usr/bin/tab-companion"

glib-compile-schemas --strict "$staging/usr/share/glib-2.0/schemas"
desktop-file-validate "$staging/usr/share/applications/io.github.agcarbajo.TabCompanion.desktop"
appstreamcli validate --no-net "$staging/usr/share/metainfo/io.github.agcarbajo.TabCompanion.metainfo.xml"
python3 -m compileall -q "$staging/usr/lib/tab-companion"

chown -R root:root "$staging"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -exec chmod 0644 {} +
chmod 0755 "$staging/usr/bin/tab-companion" \
	"$staging/usr/libexec/tab-companion-hardware" \
	"$staging/usr/libexec/tab-companion-spen-pairing" \
	"$staging/usr/libexec/tab-companion-spen-permissions" \
	"$staging/DEBIAN/postinst" "$staging/DEBIAN/postrm"
find "$staging" -exec touch -h -d '@0' {} +

dpkg-deb --root-owner-group --build "$staging" "$deb"
dpkg-deb --contents "$deb"
sha256sum "$deb"
