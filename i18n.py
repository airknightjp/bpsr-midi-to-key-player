from __future__ import annotations


LANGUAGE_NAMES = {
    "en": "English",
    "ja": "\u65e5\u672c\u8a9e",
    "zh": "\u4e2d\u6587",
}


COLOR_THEME_NAMES = {
    "en": {
        "sky_blue": "Sky Blue",
        "light": "Light",
        "dark": "Dark",
        "green": "Green",
        "yellow": "Yellow",
        "blue": "Blue",
        "red": "Red",
        "pink": "Pink",
        "orange": "Orange",
    },
    "ja": {
        "sky_blue": "\u30b9\u30ab\u30a4\u30d6\u30eb\u30fc",
        "light": "\u30e9\u30a4\u30c8",
        "dark": "\u30c0\u30fc\u30af",
        "green": "\u30b0\u30ea\u30fc\u30f3",
        "yellow": "\u30a4\u30a8\u30ed\u30fc",
        "blue": "\u30d6\u30eb\u30fc",
        "red": "\u30ec\u30c3\u30c9",
        "pink": "\u30d4\u30f3\u30af",
        "orange": "\u30aa\u30ec\u30f3\u30b8",
    },
    "zh": {
        "sky_blue": "\u5929\u84dd\u8272",
        "light": "\u6d45\u8272",
        "dark": "\u6df1\u8272",
        "green": "\u7eff\u8272",
        "yellow": "\u9ec4\u8272",
        "blue": "\u84dd\u8272",
        "red": "\u7ea2\u8272",
        "pink": "\u7c89\u8272",
        "orange": "\u6a59\u8272",
    },
}


SOUND_SOURCE_NAMES = {
    "en": {
        "piano": "Piano",
        "electric_piano": "Electric Piano",
        "organ": "Organ",
        "synth": "Synth",
    },
    "ja": {
        "piano": "ピアノ",
        "electric_piano": "エレクトリックピアノ",
        "organ": "オルガン",
        "synth": "シンセ",
    },
    "zh": {
        "piano": "钢琴",
        "electric_piano": "电钢琴",
        "organ": "风琴",
        "synth": "合成器",
    },
}


RELEASE_NOTES_CONTENT = {
    "en": """v1.4.0

This release adds secure in-app updates through GitHub Releases.

[Main changes]

- The app checks GitHub Releases for a newer version at startup and displays
  a notification only when an update is available.
- Added Other > Check for Updates for manual update checks.
- Automatic checks are limited to once per hour. The last check time is saved
  in settings.json, while manual checks remain available at any time.
- Added confirmation before updating and a single progress window for the
  download, verification, installation, and restart process.
- Release ZIP size, SHA-256 digest, archive structure, and paths are validated
  before replacing application files.
- Local settings are preserved during updates. After a successful update, the
  app restarts automatically and is brought to the foreground.
- Failed updates restore the previous application files and report the error
  on the next launch.

[v1.3.1]

This emergency release fixes MIDI input conversion shortcuts and player
control feedback.

[Fixes in v1.3.1]

- Global Start, Pause, and End shortcuts now affect MIDI input conversion only.
  Realtime input conversion and MIDI sound playback are not interrupted.
- Start no longer stops an active MIDI input conversion. When conversion is
  paused, Start restarts it from the beginning.
- MIDI input conversion shortcuts are blocked only while MIDI sound playback
  is active and remain available while sound playback is paused.
- The shared Start button now shows a pause icon while MIDI input conversion is
  paused, making the interrupted state visible.
- Fixed square hover backgrounds appearing on player controls immediately
  after the first launch.

[v1.3.0]

This release adds an in-app software synthesizer, automatic audio tuning,
performance visualization and scoring, and automatic sustain generation.

[Main changes]

- Replaced WinMM-based MIDI playback and realtime preview audio with an
  in-app software synthesizer.
- Added four selectable sound sources: Piano, Electric Piano, Organ, and Synth.
- Added automatic tuning for the Qt audio queue and internal Buffer. The app
  monitors audio starvation, output underruns, and synthesis load to balance
  latency and stability for the current environment.
- The smallest stable Qt value is learned for each audio environment and saved
  as the starting value for the next launch.
- The output device's preferred audio format is used first, with automatic
  fallback to Float32, Int16, or Int32 when necessary.
- Added Automatic sustain generation. Harmony, semitone clashes, bass overlap,
  held-note count, duration, and pitch range are analyzed to avoid muddy pedal
  use. Existing CC64 pedal events take priority.
- Added a full A0-C8 keyboard and falling-note rhythm-game display. Both show
  the notes produced by the final output mapping.
- Added PERFECT, GREAT, and GOOD timing judgments, combo multipliers, and
  scoring for note press, hold, and release timing.
- MIDI-only playback and MIDI input conversion are displayed as automatic
  PERFECT performances.
- Added Previous, Play/Pause, Next, Continuous playback, Repeat one, and
  Continuous playback off controls.
- Unified realtime input conversion and MIDI input conversion under one Start
  button while showing the options for the selected mode.
- Realtime USB MIDI input conversion can now be used during MIDI sound playback.
- Sustain, Octave down, and Octave up keys can now be changed in Key Bindings.
- Main panels can be reordered by drag and drop and individually shown or
  hidden from the View menu. Their order and visibility are saved.
- Rhythm-game and keyboard calculations stop while those panels are hidden and
  resynchronize when shown again.
- Added File > Save Settings. Normal setting changes are saved together when
  the application exits.
- Added this release-notes window at startup. Select Don't show again to disable
  the automatic display.

[Fixes]

- Fixed MIDI list rows not receiving the selected state correctly.
- Seeking is now applied only when the playback-position drag is released.
- Fixed repeated and very short notes not updating the keyboard correctly.
- Active MIDI playback, realtime input, keyboard, and rhythm-game displays now
  immediately reflect supported setting changes.
- Moved audio processing to a worker, command queue, PCM ring buffer, and Qt
  push output to reduce dropouts, latency, and processing load.

[Important changes]

- Distribution changed from a single executable to an install-free extracted
  folder. Keep the executable and _internal folder together.
- settings.json is now stored in the extracted application folder. Settings
  from the previous location are not migrated automatically.""",
    "ja": """v1.4.0

本バージョンでは、GitHub Releasesを利用した安全なアプリ内更新機能を
追加しました。

【主な変更】

- 起動時にGitHub Releasesの最新バージョンを確認し、
  更新がある場合だけ通知するようにしました。
- 「その他 > 更新を確認」から、いつでも手動で更新を確認できます。
- 自動確認は1時間に1回までに制限し、最終確認時刻をsettings.jsonへ
  保存します。手動確認はこの制限に関係なく実行できます。
- 更新前の確認画面と、ダウンロード、検証、適用、再起動の進捗を
  1つのウィンドウで確認できる更新画面を追加しました。
- 配布ZIPのファイルサイズ、SHA-256、構成、パスの安全性を検証してから
  アプリのファイルを置き換えます。
- ローカル設定を保持したまま更新し、完了後はアプリを自動再起動して
  前面へ表示します。
- 更新に失敗した場合は以前のアプリファイルへ復旧し、
  次回起動時にエラー内容を通知します。

【v1.3.1】

本バージョンは、MIDI入力変換のショートカット制御と
プレイヤー操作表示の不具合を修正する緊急リリースです。

【v1.3.1の修正】

- グローバル開始／中断／終了ショートカットの対象を
  MIDI入力変換だけに限定しました。リアルタイム入力変換と
  MIDI音源再生には影響しません。
- 実行中に開始ショートカットを押しても停止しないようにしました。
  中断中に開始した場合は、先頭からMIDI入力変換を再開します。
- MIDI音源再生中だけMIDI入力変換ショートカットを無効にし、
  MIDI音源の一時停止中は使用できるようにしました。
- MIDI入力変換の中断中は、共通の開始ボタンへ中断アイコンを表示し、
  中断状態を視覚的に確認できるようにしました。
- 初回起動直後にプレイヤー操作へマウスを重ねると、
  四角い背景が表示される問題を修正しました。

【v1.3.0】

本バージョンでは、アプリ内ソフトウェア音源、音声出力の自動最適化、
演奏の可視化・採点機能、サスティンの自動生成を追加しました。

【主な変更】

- MIDI音源再生とリアルタイム試聴音を、WinMMに依存しない
  アプリ内ソフトウェアシンセへ変更しました。
- ピアノ、エレクトリックピアノ、オルガン、シンセの
  4種類から音源を選択できるようになりました。
- Qtの音声待機量と内部Bufferを自動調整する機能を追加しました。
  音声供給不足、出力空状態、波形生成負荷を監視し、
  利用環境に合わせて遅延と安定性のバランスを自動調整します。
- 利用環境で安定する最小のQt値を学習し、次回起動時の開始値として
  設定ファイルへ保存するようになりました。
- 出力デバイスの推奨音声形式を優先し、利用できない場合は
  Float32、Int16、Int32から対応形式を自動選択します。
- 「サスティンの自動生成」を追加しました。
  和声、半音衝突、低音の重なり、保持音数、保持時間などを解析し、
  音が濁りにくいペダル操作を自動生成します。
  元の演奏にCC64が含まれる場合は、そのペダル操作を優先します。
- A0-C8のフル鍵盤表示と、上から音が流れる音ゲー表示を追加しました。
  実際の最終出力音を鍵盤と音ゲー画面へ反映します。
- MIDI再生とリアルタイム入力のタイミングを比較する採点機能を
  追加しました。PERFECT、GREAT、GOODの判定、コンボ倍率、
  押下、長押し、離上の採点に対応しています。
- MIDI音源再生のみの場合とMIDI入力変換では、
  演奏内容を自動的にPERFECTとして表示します。
- 前の曲、再生／一時停止、次の曲、連続再生、
  1曲ループ再生の操作を追加しました。
- リアルタイム入力変換とMIDI入力変換を共通の開始ボタンへ統合し、
  選択した入力方式の設定だけを表示するようにしました。
- MIDI音源再生中も、USB MIDIキーボードのリアルタイム入力変換を
  同時に利用できるようになりました。
- サスティン、音域下げ、音域上げのキーを
  キーバインド画面から変更できるようになりました。
- 各パネルの並び順をドラッグ＆ドロップで変更できるようになりました。
  表示メニューから各パネルを個別に表示／非表示にでき、
  並び順と表示状態は設定へ保存されます。
- 音ゲーまたは鍵盤を非表示にした場合は関連する描画と計算を停止し、
  再表示時に現在の演奏位置へ同期するようになりました。
- 「ファイル」メニューへ「設定を保存」を追加しました。
  通常の設定保存はアプリ終了時にまとめて行います。
- 起動時にリリースノートを表示する機能を追加しました。
  「今後表示しない」を選択した場合は、次回から自動表示されません。

【主な修正】

- MIDI一覧をクリックしても選択状態が正しく移動しない問題を修正しました。
- 再生位置のドラッグ中に再生処理へ影響していた問題を修正し、
  ドロップ時にのみシークするようにしました。
- 同じ音の再発音や短い発音が、鍵盤表示へ正しく反映されない問題を
  修正しました。
- 設定変更が再生中のMIDI、リアルタイム入力、鍵盤、
  音ゲー表示へ即時反映されない問題を修正しました。
- 音声処理を専用ワーカー、コマンドキュー、PCMリングバッファ、
  Qtへのプッシュ出力へ変更し、音切れ、遅延、処理負荷を改善しました。

【重要な変更】

- 配布形式を単体EXEから、インストール不要のフォルダ展開版へ
  変更しました。EXEと_internalフォルダを同じ場所で使用してください。
- 設定ファイルの保存先を、アプリの展開先にあるsettings.jsonへ
  変更しました。旧保存先の設定は自動移行されません。""",
    "zh": """v1.4.0

本版本新增了通过GitHub Releases进行安全应用内更新的功能。

【主要变更】

- 启动时检查GitHub Releases中的最新版本，仅在有可用更新时通知。
- 可通过“其他 > 检查更新”随时手动检查更新。
- 自动检查限制为每小时一次，并将上次检查时间保存到settings.json。
  手动检查不受此限制。
- 更新前显示确认窗口，并在一个进度窗口中显示下载、验证、安装和重启状态。
- 替换应用文件前会验证发布ZIP的文件大小、SHA-256、目录结构和路径安全性。
- 更新时保留本地设置，成功后自动重启应用并将窗口显示到前台。
- 更新失败时恢复之前的应用文件，并在下次启动时显示错误信息。

【v1.3.1】

本版本是紧急修复版本，修正了MIDI输入转换快捷键控制和
播放器操作显示的问题。

【v1.3.1修复】

- 全局开始、暂停和结束快捷键现在仅作用于MIDI输入转换，
  不会中断实时输入转换或MIDI音源播放。
- MIDI输入转换运行时再次按开始键不会停止；暂停后按开始键会从头开始。
- 仅在MIDI音源正在播放时禁用MIDI输入转换快捷键，
  MIDI音源暂停时仍可使用。
- MIDI输入转换暂停时，共用开始按钮会显示暂停图标，
  便于确认当前处于暂停状态。
- 修复首次启动后将鼠标移到播放器控制按钮上时出现方形背景的问题。

【v1.3.0】

本版本新增了应用内软件合成器、音频输出自动优化、
演奏可视化与评分，以及自动延音生成功能。

【主要变更】

- 将MIDI音源播放和实时试听音频从WinMM改为应用内软件合成器。
- 新增钢琴、电钢琴、风琴和合成器四种可选音源。
- 新增Qt音频等待量和内部Buffer的自动调节。应用会监控音频供给不足、
  输出欠载和波形生成负载，并根据当前环境自动平衡延迟与稳定性。
- 学习当前音频环境中可稳定使用的最小Qt值，并保存为下次启动值。
- 优先使用输出设备的推荐音频格式，必要时自动回退到
  Float32、Int16或Int32。
- 新增“自动延音生成”。系统会分析和声、半音冲突、低音重叠、
  保持音数量、保持时间和音域，生成不易造成声音浑浊的踏板操作。
  原始演奏中包含CC64时，优先使用原有踏板操作。
- 新增A0-C8完整键盘和下落式音符显示，并反映最终输出映射后的音符。
- 新增PERFECT、GREAT、GOOD判定、连击倍率，以及按下、长按和松开评分。
- 仅播放MIDI音源或执行MIDI输入转换时，演奏会自动显示为PERFECT。
- 新增上一首、播放／暂停、下一首、连续播放、单曲循环和
  关闭连续播放操作。
- 将实时输入转换与MIDI输入转换合并为一个开始按钮，
  并仅显示当前所选输入方式的设置。
- MIDI音源播放期间也可以同时使用USB MIDI键盘实时输入转换。
- 可在按键绑定画面中修改延音、降低八度和升高八度按键。
- 支持通过拖放调整主面板顺序，也可从“显示”菜单单独显示或隐藏面板。
  面板顺序与显示状态会保存到设置中。
- 音乐游戏或键盘面板隐藏时会停止相关绘制与计算，
  重新显示时同步到当前演奏位置。
- 在“文件”菜单中新增“保存设置”。普通设置变更会在应用退出时统一保存。
- 新增启动时显示的发行说明窗口。勾选“以后不再显示”后，
  下次启动时不会自动显示。

【主要修复】

- 修复点击MIDI列表后选择状态不能正确移动的问题。
- 拖动播放位置时不再立即影响播放，仅在释放后执行跳转。
- 修复重复音和极短音符不能正确更新键盘显示的问题。
- 支持的设置变更会立即反映到MIDI播放、实时输入、键盘和音乐游戏显示。
- 将音频处理改为专用工作线程、命令队列、PCM环形缓冲区和Qt推送输出，
  以降低断音、延迟和处理负载。

【重要变更】

- 发布形式由单文件EXE改为免安装文件夹版。请将EXE与_internal文件夹
  保持在同一位置。
- settings.json改为保存在应用展开目录中，旧位置的设置不会自动迁移。""",
}


TEXT = {
    "en": {
        "title": "BPSR MIDI to KEY Player",
        "menu_midi": "File",
        "menu_view": "View",
        "menu_settings": "Settings",
        "menu_other": "Other",
        "release_notes": "Release Notes",
        "release_notes_content": RELEASE_NOTES_CONTENT["en"],
        "dont_show_again": "Don't show again",
        "about_app": "About BPSR MIDI to KEY Player",
        "about_title": "About BPSR MIDI to KEY Player",
        "version": "Version",
        "close": "Close",
        "exit": "Exit",
        "save_settings": "Save Settings",
        "load_midi": "Select MIDI Folder",
        "play_keys": "Start Playback",
        "play_midi_sound": "Play MIDI",
        "stop_keys": "End",
        "stop_midi": "Stop MIDI",
        "color_theme": "Theme",
        "sound_source": "Sound Source",
        "audio_runtime": "Qt {qt} | Buffer {buffer}",
        "check_for_updates": "Check for Updates",
        "no_updates": "No updates are available.",
        "update_check_failed": "Could not check for updates.\n{error}",
        "update_title": "Software Update",
        "update_confirm": (
            "Update from v{current} to v{version}?\n"
            "The app will restart automatically after the update."
        ),
        "update_install_failed": "The updater could not be started.",
        "update_not_supported": (
            "Automatic update is available only in the distributed app."
        ),
        "update_error_title": "Update Failed",
        "always_on_top": "Always on top",
        "tray_resident": "Close to tray",
        "window_opacity": "Opacity",
        "ui_scale": "Scale",
        "basic_screen_panel": "Basic Screen",
        "advanced_settings_panel": "Advanced Settings",
        "rhythm_game_panel": "Rhythm Game",
        "keyboard_panel": "Keyboard",
        "player_panel": "Player",
        "key_playback_settings": "MIDI Input Conversion",
        "midi_sound_settings": "Advanced Settings",
        "midi_input_settings": "Realtime Input Conversion",
        "player_section": "Player",
        "midi_input_device": "Input device",
        "start_midi_input": "Start Listening",
        "stop_midi_input": "End",
        "no_midi_input_devices": "No MIDI input devices",
        "dry_run": "Test mode (sound/log only)",
        "countdown": "Countdown",
        "seconds_unit": "sec",
        "countdown_sound": "Sound",
        "game_countdown_sound": "Play sound in game (ensemble)",
        "humanize_timing": "Timing variation",
        "chord_optimization": "Chord reconstruction",
        "chord_strum": "Chord spread",
        "auto_sustain": "Automatic sustain generation",
        "repeat_prevention": "Prevent rapid repeats",
        "playback_speed": "SPD",
        "auto_fit_note_range": "Fit to 3 octaves",
        "transpose_semitones": "Transpose",
        "octave_shift": "Octave shift",
        "shortcut_settings": "Shortcut",
        "shortcut_start": "Start",
        "shortcut_pause_resume": "Pause",
        "shortcut_end": "End",
        "shortcut_lock": "Lock",
        "language": "Language",
        "key_bindings": "Key Bindings",
        "restore_default_key_bindings": "Restore Defaults",
        "key_binding_sustain": "Sustain",
        "key_binding_octave_down": "Octave down",
        "key_binding_octave_up": "Octave up",
        "octave": "Octave",
        "midi_sound_volume": "VOL",
        "previous_track": "Previous track",
        "play_sound": "Play",
        "pause_sound": "Pause",
        "next_track": "Next track",
        "playback_mode_off": "Continuous playback off",
        "playback_mode_continuous": "Continuous playback",
        "playback_mode_repeat_one": "Repeat one",
        "playback_log": "Log",
        "midi_list": "MIDI List",
        "name": "Name",
        "note_range": "Range",
        "duration": "Duration",
        "folder_loaded_log": "Loaded folder {folder}: {count} MIDI files",
        "no_midi_files": "No MIDI files were found in the selected folder.",
        "select_midi_file": "Select MIDI folder",
        "load_failed_title": "Load failed",
        "no_midi_title": "No MIDI",
        "load_midi_first": "Load a MIDI file first.",
        "no_events_title": "No events",
        "no_events_enabled": "No events are enabled for playback.",
        "already_playing_title": "Already playing",
        "waiting": "waiting..",
        "optimization_progress": "Optimizing {percent}%",
        "loaded_log": "Loaded {name}: {event_count} events, {duration:.2f}s, channels {channels}",
        "none": "none",
        "key_playback_started": "Key playback started ({mode})",
        "sound_playback_stopped": "MIDI sound playback stopped",
        "dry_run_mode": "test mode",
        "real_keyboard_output": "real keyboard output",
    },
    "ja": {
        "title": "BPSR MIDI to KEY Player",
        "menu_midi": "\u30d5\u30a1\u30a4\u30eb",
        "menu_view": "\u8868\u793a",
        "menu_settings": "\u8a2d\u5b9a",
        "menu_other": "\u305d\u306e\u4ed6",
        "release_notes": "\u30ea\u30ea\u30fc\u30b9\u30ce\u30fc\u30c8",
        "release_notes_content": RELEASE_NOTES_CONTENT["ja"],
        "dont_show_again": "\u4eca\u5f8c\u8868\u793a\u3057\u306a\u3044",
        "about_app": "BPSR MIDI to KEY Player \u306b\u3064\u3044\u3066",
        "about_title": "BPSR MIDI to KEY Player \u306b\u3064\u3044\u3066",
        "version": "\u30d0\u30fc\u30b8\u30e7\u30f3",
        "close": "\u9589\u3058\u308b",
        "exit": "\u7d42\u4e86",
        "save_settings": "\u8a2d\u5b9a\u3092\u4fdd\u5b58",
        "load_midi": "MIDI\u30d5\u30a9\u30eb\u30c0\u6307\u5b9a",
        "play_keys": "\u518d\u751f\u958b\u59cb",
        "play_midi_sound": "MIDI\u518d\u751f",
        "stop_keys": "\u7d42\u4e86",
        "stop_midi": "MIDI\u505c\u6b62",
        "color_theme": "\u30c6\u30fc\u30de",
        "sound_source": "\u97f3\u6e90",
        "audio_runtime": "Qt {qt} | Buffer {buffer}",
        "check_for_updates": "\u66f4\u65b0\u3092\u78ba\u8a8d",
        "no_updates": "\u66f4\u65b0\u306f\u3042\u308a\u307e\u305b\u3093\u3002",
        "update_check_failed": (
            "\u66f4\u65b0\u306e\u78ba\u8a8d\u306b\u5931\u6557\u3057\u307e\u3057\u305f\u3002\n{error}"
        ),
        "update_title": "\u30bd\u30d5\u30c8\u30a6\u30a7\u30a2\u66f4\u65b0",
        "update_confirm": (
            "v{current} \u304b\u3089 v{version} \u3078\u66f4\u65b0\u3057\u307e\u3059\u304b\uff1f\n"
            "\u66f4\u65b0\u5b8c\u4e86\u5f8c\u3001\u30a2\u30d7\u30ea\u3092\u81ea\u52d5\u7684\u306b\u518d\u8d77\u52d5\u3057\u307e\u3059\u3002"
        ),
        "update_install_failed": "\u30a2\u30c3\u30d7\u30c7\u30fc\u30bf\u30fc\u3092\u8d77\u52d5\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002",
        "update_not_supported": "\u81ea\u52d5\u66f4\u65b0\u306f\u914d\u5e03\u7248\u3067\u306e\u307f\u5229\u7528\u3067\u304d\u307e\u3059\u3002",
        "update_error_title": "\u30a2\u30c3\u30d7\u30c7\u30fc\u30c8\u5931\u6557",
        "always_on_top": "\u6700\u524d\u9762\u306b\u8868\u793a",
        "tray_resident": "[\u9589\u3058\u308b]\u3067\u30bf\u30b9\u30af\u30c8\u30ec\u30a4\u306b\u683c\u7d0d",
        "window_opacity": "\u900f\u904e\u5ea6",
        "ui_scale": "\u62e1\u5927\u7387",
        "basic_screen_panel": "\u57fa\u672c\u753b\u9762",
        "advanced_settings_panel": "\u8a73\u7d30\u8a2d\u5b9a",
        "rhythm_game_panel": "\u97f3\u30b2\u30fc",
        "keyboard_panel": "\u9375\u76e4",
        "player_panel": "\u30d7\u30ec\u30a4\u30e4\u30fc",
        "key_playback_settings": "MIDI\u5165\u529b\u5909\u63db",
        "midi_sound_settings": "\u8a73\u7d30\u8a2d\u5b9a",
        "midi_input_settings": "\u30ea\u30a2\u30eb\u30bf\u30a4\u30e0\u5165\u529b\u5909\u63db",
        "player_section": "\u30d7\u30ec\u30a4\u30e4\u30fc",
        "midi_input_device": "\u5165\u529b\u30c7\u30d0\u30a4\u30b9",
        "start_midi_input": "\u53d7\u4ed8\u958b\u59cb",
        "stop_midi_input": "\u7d42\u4e86",
        "no_midi_input_devices": "MIDI\u5165\u529b\u30c7\u30d0\u30a4\u30b9\u306a\u3057",
        "dry_run": "\u30c6\u30b9\u30c8\u30e2\u30fc\u30c9(\u97f3\u30fb\u30ed\u30b0\u306e\u307f)",
        "countdown": "\u30ab\u30a6\u30f3\u30c8\u30c0\u30a6\u30f3",
        "seconds_unit": "\u79d2",
        "countdown_sound": "\u97f3\u3092\u9cf4\u3089\u3059",
        "game_countdown_sound": "\u30b2\u30fc\u30e0\u5185\u3067\u97f3\u3092\u9cf4\u3089\u3059(\u5408\u594f\u7528)",
        "humanize_timing": "\u30bf\u30a4\u30df\u30f3\u30b0\u306e\u5206\u6563",
        "chord_optimization": "\u548c\u97f3\u306e\u518d\u69cb\u6210",
        "chord_strum": "\u548c\u97f3\u306e\u5206\u6563",
        "auto_sustain": "\u30b5\u30b9\u30c6\u30a3\u30f3\u306e\u81ea\u52d5\u751f\u6210",
        "repeat_prevention": "\u9023\u6253\u6291\u6b62",
        "playback_speed": "\u901f\u5ea6",
        "auto_fit_note_range": "\u97f3\u57df\u30923\u30aa\u30af\u30bf\u30fc\u30d6\u306b\u7e2e\u3081\u308b",
        "transpose_semitones": "\u30c8\u30e9\u30f3\u30b9\u30dd\u30fc\u30ba",
        "octave_shift": "\u30aa\u30af\u30bf\u30fc\u30d6\u30b7\u30d5\u30c8",
        "shortcut_settings": "\u30b7\u30e7\u30fc\u30c8\u30ab\u30c3\u30c8",
        "shortcut_start": "\u958b\u59cb",
        "shortcut_pause_resume": "\u4e2d\u65ad",
        "shortcut_end": "\u7d42\u4e86",
        "shortcut_lock": "\u30ed\u30c3\u30af",
        "language": "\u8a00\u8a9e",
        "key_bindings": "\u30ad\u30fc\u30d0\u30a4\u30f3\u30c9",
        "restore_default_key_bindings": "\u30c7\u30d5\u30a9\u30eb\u30c8\u306b\u623b\u3059",
        "key_binding_sustain": "\u30b5\u30b9\u30c6\u30a3\u30f3",
        "key_binding_octave_down": "\u97f3\u57df\u4e0b\u3052",
        "key_binding_octave_up": "\u97f3\u57df\u4e0a\u3052",
        "octave": "\u30aa\u30af\u30bf\u30fc\u30d6",
        "midi_sound_volume": "\u97f3\u91cf",
        "previous_track": "\u524d\u306e\u66f2",
        "play_sound": "\u518d\u751f",
        "pause_sound": "\u4e00\u6642\u505c\u6b62",
        "next_track": "\u6b21\u306e\u66f2",
        "playback_mode_off": "\u9023\u7d9a\u518d\u751f\u30aa\u30d5",
        "playback_mode_continuous": "\u9023\u7d9a\u518d\u751f",
        "playback_mode_repeat_one": "1\u66f2\u30eb\u30fc\u30d7\u518d\u751f",
        "playback_log": "\u30ed\u30b0",
        "midi_list": "MIDI\u4e00\u89a7",
        "name": "\u540d\u524d",
        "note_range": "\u97f3\u57df",
        "duration": "\u9577\u3055",
        "folder_loaded_log": "Loaded folder {folder}: {count} MIDI files",
        "no_midi_files": "\u9078\u629e\u3057\u305f\u30d5\u30a9\u30eb\u30c0\u306bMIDI\u30d5\u30a1\u30a4\u30eb\u304c\u3042\u308a\u307e\u305b\u3093\u3002",
        "select_midi_file": "MIDI\u30d5\u30a9\u30eb\u30c0\u3092\u9078\u629e",
        "load_failed_title": "\u8aad\u307f\u8fbc\u307f\u5931\u6557",
        "no_midi_title": "MIDI\u672a\u9078\u629e",
        "load_midi_first": "\u5148\u306bMIDI\u30d5\u30a1\u30a4\u30eb\u3092\u8aad\u307f\u8fbc\u3093\u3067\u304f\u3060\u3055\u3044\u3002",
        "no_events_title": "\u30a4\u30d9\u30f3\u30c8\u306a\u3057",
        "no_events_enabled": "\u518d\u751f\u5bfe\u8c61\u306e\u30a4\u30d9\u30f3\u30c8\u304c\u3042\u308a\u307e\u305b\u3093\u3002",
        "already_playing_title": "\u518d\u751f\u4e2d",
        "waiting": "waiting..",
        "optimization_progress": "\u6700\u9069\u5316\u4e2d {percent}%",
        "loaded_log": "Loaded {name}: {event_count} events, {duration:.2f}s, channels {channels}",
        "none": "\u306a\u3057",
        "key_playback_started": "Key playback started ({mode})",
        "sound_playback_stopped": "MIDI sound playback stopped",
        "dry_run_mode": "test mode",
        "real_keyboard_output": "real keyboard output",
    },
    "zh": {
        "title": "BPSR MIDI to KEY Player",
        "menu_midi": "\u6587\u4ef6",
        "menu_view": "\u663e\u793a",
        "menu_settings": "\u8bbe\u7f6e",
        "menu_other": "\u5176\u4ed6",
        "release_notes": "\u53d1\u884c\u8bf4\u660e",
        "release_notes_content": RELEASE_NOTES_CONTENT["zh"],
        "dont_show_again": "\u4ee5\u540e\u4e0d\u518d\u663e\u793a",
        "about_app": "\u5173\u4e8e BPSR MIDI to KEY Player",
        "about_title": "\u5173\u4e8e BPSR MIDI to KEY Player",
        "version": "\u7248\u672c",
        "close": "\u5173\u95ed",
        "exit": "\u9000\u51fa",
        "save_settings": "\u4fdd\u5b58\u8bbe\u7f6e",
        "load_midi": "\u6307\u5b9a MIDI \u6587\u4ef6\u5939",
        "play_keys": "\u5f00\u59cb\u64ad\u653e",
        "play_midi_sound": "\u64ad\u653e MIDI",
        "stop_keys": "\u7ed3\u675f",
        "stop_midi": "\u505c\u6b62 MIDI",
        "color_theme": "\u4e3b\u9898",
        "sound_source": "\u97f3\u6e90",
        "audio_runtime": "Qt {qt} | Buffer {buffer}",
        "check_for_updates": "\u68c0\u67e5\u66f4\u65b0",
        "no_updates": "\u6ca1\u6709\u53ef\u7528\u66f4\u65b0\u3002",
        "update_check_failed": "\u65e0\u6cd5\u68c0\u67e5\u66f4\u65b0\u3002\n{error}",
        "update_title": "\u8f6f\u4ef6\u66f4\u65b0",
        "update_confirm": (
            "\u662f\u5426\u4ece v{current} \u66f4\u65b0\u5230 v{version}\uff1f\n"
            "\u66f4\u65b0\u5b8c\u6210\u540e\uff0c\u5e94\u7528\u5c06\u81ea\u52a8\u91cd\u542f\u3002"
        ),
        "update_install_failed": "\u65e0\u6cd5\u542f\u52a8\u66f4\u65b0\u7a0b\u5e8f\u3002",
        "update_not_supported": "\u81ea\u52a8\u66f4\u65b0\u4ec5\u5728\u53d1\u5e03\u7248\u5e94\u7528\u4e2d\u53ef\u7528\u3002",
        "update_error_title": "\u66f4\u65b0\u5931\u8d25",
        "always_on_top": "\u7f6e\u4e8e\u9876\u5c42",
        "tray_resident": "\u5173\u95ed\u65f6\u6700\u5c0f\u5316\u5230\u6258\u76d8",
        "window_opacity": "\u900f\u660e\u5ea6",
        "ui_scale": "\u7f29\u653e\u6bd4\u4f8b",
        "basic_screen_panel": "\u57fa\u672c\u754c\u9762",
        "advanced_settings_panel": "\u8be6\u7ec6\u8bbe\u7f6e",
        "rhythm_game_panel": "\u97f3\u4e50\u6e38\u620f",
        "keyboard_panel": "\u952e\u76d8",
        "player_panel": "\u64ad\u653e\u5668",
        "key_playback_settings": "MIDI \u8f93\u5165\u8f6c\u6362",
        "midi_sound_settings": "\u9ad8\u7ea7\u8bbe\u7f6e",
        "midi_input_settings": "\u5b9e\u65f6\u8f93\u5165\u8f6c\u6362",
        "player_section": "\u64ad\u653e\u5668",
        "midi_input_device": "\u8f93\u5165\u8bbe\u5907",
        "start_midi_input": "\u5f00\u59cb\u63a5\u6536",
        "stop_midi_input": "\u7ed3\u675f",
        "no_midi_input_devices": "\u6ca1\u6709 MIDI \u8f93\u5165\u8bbe\u5907",
        "dry_run": "\u6d4b\u8bd5\u6a21\u5f0f(\u4ec5\u58f0\u97f3\u548c\u65e5\u5fd7)",
        "countdown": "\u5012\u8ba1\u65f6",
        "seconds_unit": "\u79d2",
        "countdown_sound": "\u64ad\u653e\u58f0\u97f3",
        "game_countdown_sound": "\u5728\u6e38\u620f\u5185\u64ad\u653e\u58f0\u97f3(\u5408\u594f\u7528)",
        "humanize_timing": "\u65f6\u5e8f\u5206\u6563",
        "chord_optimization": "\u548c\u5f26\u91cd\u6784",
        "chord_strum": "\u548c\u5f26\u5206\u6563",
        "auto_sustain": "\u81ea\u52a8\u5ef6\u97f3\u751f\u6210",
        "repeat_prevention": "\u9632\u6b62\u5feb\u901f\u8fde\u51fb",
        "playback_speed": "\u901f\u5ea6",
        "auto_fit_note_range": "\u7f29\u5c0f\u5230 3 \u4e2a\u516b\u5ea6",
        "transpose_semitones": "\u79fb\u8c03",
        "octave_shift": "\u516b\u5ea6\u79fb\u4f4d",
        "shortcut_settings": "\u5feb\u6377\u952e",
        "shortcut_start": "\u5f00\u59cb",
        "shortcut_pause_resume": "\u6682\u505c",
        "shortcut_end": "\u7ed3\u675f",
        "shortcut_lock": "\u9501\u5b9a",
        "language": "\u8bed\u8a00",
        "key_bindings": "\u6309\u952e\u7ed1\u5b9a",
        "restore_default_key_bindings": "\u6062\u590d\u9ed8\u8ba4",
        "key_binding_sustain": "\u5ef6\u97f3",
        "key_binding_octave_down": "\u964d\u4f4e\u516b\u5ea6",
        "key_binding_octave_up": "\u5347\u9ad8\u516b\u5ea6",
        "octave": "\u516b\u5ea6",
        "midi_sound_volume": "\u97f3\u91cf",
        "previous_track": "\u4e0a\u4e00\u9996",
        "play_sound": "\u64ad\u653e",
        "pause_sound": "\u6682\u505c",
        "next_track": "\u4e0b\u4e00\u9996",
        "playback_mode_off": "\u5173\u95ed\u8fde\u7eed\u64ad\u653e",
        "playback_mode_continuous": "\u8fde\u7eed\u64ad\u653e",
        "playback_mode_repeat_one": "\u5355\u66f2\u5faa\u73af",
        "playback_log": "\u65e5\u5fd7",
        "midi_list": "MIDI \u5217\u8868",
        "name": "\u540d\u79f0",
        "note_range": "\u97f3\u57df",
        "duration": "\u65f6\u957f",
        "folder_loaded_log": "Loaded folder {folder}: {count} MIDI files",
        "no_midi_files": "\u6240\u9009\u6587\u4ef6\u5939\u4e2d\u6ca1\u6709 MIDI \u6587\u4ef6\u3002",
        "select_midi_file": "\u9009\u62e9 MIDI \u6587\u4ef6\u5939",
        "load_failed_title": "\u52a0\u8f7d\u5931\u8d25",
        "no_midi_title": "\u672a\u9009\u62e9 MIDI",
        "load_midi_first": "\u8bf7\u5148\u52a0\u8f7d MIDI \u6587\u4ef6\u3002",
        "no_events_title": "\u6ca1\u6709\u4e8b\u4ef6",
        "no_events_enabled": "\u6ca1\u6709\u542f\u7528\u53ef\u64ad\u653e\u7684\u4e8b\u4ef6\u3002",
        "already_playing_title": "\u6b63\u5728\u64ad\u653e",
        "waiting": "waiting..",
        "optimization_progress": "\u4f18\u5316\u4e2d {percent}%",
        "loaded_log": "Loaded {name}: {event_count} events, {duration:.2f}s, channels {channels}",
        "none": "\u65e0",
        "key_playback_started": "Key playback started ({mode})",
        "sound_playback_stopped": "MIDI sound playback stopped",
        "dry_run_mode": "test mode",
        "real_keyboard_output": "real keyboard output",
    },
}


def normalize_language(language: object) -> str:
    if isinstance(language, str) and language in TEXT:
        return language
    return "en"


def normalize_color_theme(theme: object) -> str:
    if isinstance(theme, str) and theme in COLOR_THEME_NAMES["en"]:
        return theme
    return "sky_blue"
