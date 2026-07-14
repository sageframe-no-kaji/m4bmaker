# m4Bookmaker — description

A desktop app that converts folders of MP3 (or other audio) files into clean, properly chaptered M4B audiobooks you own outright.

A small app with a large argument. m4Bookmaker exists because Audible's ecosystem treats audiobook ownership as a license rather than a possession — a contract that can be revoked, a format that will not move, a library that lives on someone else's server at someone else's discretion. The technical solution is small — rebuild the M4B yourself from MP3s — and the position is large: you own what you can hold, file by file, on your own machine. The full pipeline handles automatic chapter detection from filenames, an interactive visual chapter editor with a built-in audio player, batch queue processing, and automatic repair of common encoding problems, with a deliberate GUI-to-CLI symmetry that keeps it scriptable without sacrificing approachability. It was one of the first tools built under the Ho System — concept to signed, packaged, distributed product in 3.5 days — and the position it embodies is structural: every time a tool gets repossessed by its platform, a small piece of personal capacity dies, and m4Bookmaker is the refusal of that pattern, sized to one specific failure.

Python with PyQt5 and FFmpeg; shipped as a signed macOS app and a Windows installer, and distributed as a PyPI package.
