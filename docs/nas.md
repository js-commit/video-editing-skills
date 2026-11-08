# Using a NAS (optional)

A NAS (network-attached storage) is a box of hard drives on your home
network. It is a good home for finished-project archives, the b-roll library
and home videos: lots of space, reachable from every computer. It is **not**
needed: every skill works with local or external drives.

## How the skills use it

- In `/setup` you say whether you have one and where it shows up on this
  computer when connected (`nas.enabled`, `nas.mount_path`). Archive,
  b-roll library and home-video folders can then point inside it.
- Before writing to the NAS, skills check that the path exists. If it isn't
  mounted they stop and ask you to connect it; they never write to a local
  folder of the same name by mistake.
- Big moves (archiving) copy first, verify the copy (size, and checksums if
  `archive.checksum` is on), and only then offer to delete the local
  originals, after showing you the list.
- Never store your NAS's address, user name or password in this repo. Your
  operating system remembers the login.

## Connect (mount) the share

A NAS offers **shares** (top-level folders) over **SMB**, the standard
file-sharing protocol on macOS, Windows and Linux. Use the NAS's network name
(often `<name>.local`) or address, from its own admin page.

### macOS

1. Finder > Go > Connect to Server (⌘K).
2. Enter `smb://<nas-name>.local/<share>` and click Connect; sign in and
   tick "Remember this password in my keychain".
3. The share appears under `/Volumes/<share>`. That is your `nas.mount_path`.
4. Reconnect automatically at login: System Settings > General > Login Items
   > add the mounted share (drag it from Finder's sidebar).

Optional: stop macOS writing `.DS_Store` files onto network shares:
`defaults write com.apple.desktopservices DSDontWriteNetworkStores -bool true`
(then log out and back in).

### Windows

1. File Explorer > This PC > Map network drive.
2. Pick a drive letter (e.g. `Z:`), folder `\\<nas-name>\<share>`, tick
   "Reconnect at sign-in", and sign in (tick "Remember my credentials").
3. `Z:\` is your `nas.mount_path`.

### Linux

- Desktop: the file manager's "Other Locations" > `smb://<nas-name>/<share>`.
  The path it mounts to (often under `/run/user/<id>/gvfs/`) works, but a
  fixed mount point is more reliable.
- Fixed mount point (needs the `cifs-utils` package):

  ```sh
  sudo mkdir -p /mnt/<share>
  sudo mount -t cifs //<nas-name>/<share> /mnt/<share> \
    -o credentials=$HOME/.smbcredentials,uid=$(id -u),gid=$(id -g)
  ```

  `~/.smbcredentials` holds `username=...` and `password=...` lines; keep it
  out of this repo and `chmod 600` it. For mounting at boot, add a line to
  `/etc/fstab` with the options `_netdev,nofail,x-systemd.automount` so a
  missing NAS doesn't stall startup.

## Reliability tips

- **Use a wired connection** for archiving and library work: Wi-Fi is fine
  for browsing but big copies over it are slow and drop more often.
- **Pick the most stable route.** If the NAS is reachable by more than one
  name or address and one of them keeps dropping or wedging, use the one that
  stays connected, and remount with it.
- **Mount before you start** a long job, and keep the computer awake
  (macOS: `caffeinate -i <command>`; or disable sleep while plugged in).
- **Don't edit directly from the NAS** over Wi-Fi: copy the project to a
  local or external SSD, edit, then archive back. Resolve plays network
  footage poorly unless you use proxies.
- **Resumable copies**: for manual moves, `rsync -a --progress` (macOS/Linux)
  or `robocopy /E /Z` (Windows) can resume after a drop; Finder and Explorer
  copies can't.
- **Verify before deleting** a local copy: same file count and sizes (the
  archive skill does this for you).
- **Disks spin down**: the first access after a while can take several
  seconds. That's normal; a timeout is not.
- **Network shares have no Trash**: anything deleted on the NAS is gone
  (unless the NAS has its own recycle bin or snapshots switched on: turning
  them on is a good idea).

## Settings involved

| Key | Example |
|---|---|
| `nas.enabled` | `true` |
| `nas.mount_path` | `/Volumes/<share>`, `Z:\`, `/mnt/<share>` |
| `paths.archive_dir` | `<mount_path>/video-archive` |
| `paths.broll_library_dir` | `<mount_path>/broll-library` |
| `paths.finals_dir` | `<mount_path>/final-videos` |
| `paths.home_videos_dir` | `<mount_path>/home-videos` |

See `docs/settings.md` for every key.
