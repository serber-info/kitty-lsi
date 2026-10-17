#!/bin/sh
set -eu
package=$1
cat /etc/os-release
dpkg-deb --info "$package"
apt-get -o APT::Sandbox::User=root install -y "$package"
/usr/bin/lsi --version
/usr/bin/lsi -lh /pictures/sample.txt
PATH=/nonexistent /usr/bin/lsi --no-images /pictures/sample.txt
[ -f /usr/share/doc/lsi/THIRD_PARTY.md ]
[ -d /usr/share/doc/lsi/mpl-source/avif-parse-2.1.0 ]
dpkg --purge lsi
[ ! -e /usr/bin/lsi ]
[ ! -e /usr/share/doc/lsi ]
echo 'PASS install via APT, lsi grid/long mode, licenses, clean purge'
