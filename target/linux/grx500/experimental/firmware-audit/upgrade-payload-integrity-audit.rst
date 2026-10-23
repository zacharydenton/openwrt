AX3000 sysupgrade payload integrity
===================================

The old sysupgrade check established that the tar archive was readable and
that its kernel and rootfs began with the expected magic bytes. Tar headers do
not checksum member payloads. A changed byte later in either component could
therefore reach UBI staging. If that bank were already stable, its bootloader
selection would still point at the damaged image.

The AX3000 image recipe now appends exactly one ``SHA256SUMS`` member before
fwtool metadata. It hashes the exact padded kernel and rootfs tar members.
``platform_check_image`` requires one checksum member, strict 64-digit
lowercase hashes for both named payloads, and matching computed values before
calling the UBI upgrade path. Its second check inside ``grx500_upgrade_tar``
also rejects a changed image when the generic validation was bypassed.
``sha256sum`` is copied into the temporary upgrade root. Older AX3000
sysupgrade archives without the manifest are rejected by this experimental
target.

Both ordinary and opt-in factory variants were rebuilt on OpenWrt
``a25fb079b1463cd5d7d69c6d9a1c28d873291ebb``. Their image audits bind the
checksums and packaged upgrade script to the source; both relocation-loader
handoff audits pass. Nine native and nine packaged-MIPS upgrade test groups
cover successful staged replacement and reject missing, duplicate, malformed
or mismatched checksum members before UBI mutation. They also reject a boot
environment partition whose offset, size, erase size, write size or flash type
differs from the stock layout before reading that environment or touching UBI.
For each final archive, packaged MIPS BusyBox
accepts the intact payloads and rejects a single changed byte in either the
kernel or rootfs. The current unapproved factory container also passes 16
stock checker/intercepted-writer cases with exact component extraction.
Hashes and test reports are bound in ``upgrade-payload-integrity-results.json``.

These hashes detect accidental corruption; they are not authenticated image
signatures. The tests do not perform a NAND write or boot the router. Actual
Ethernet, Wi-Fi, rollback and one-upload safety remain unverified, so the
factory container remains unapproved for upload.
