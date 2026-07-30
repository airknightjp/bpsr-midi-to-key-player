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
    "en": """v1.8.0

This release improves USB MIDI device hot-plug handling and adds in-app
feedback submission.

[Main changes]

- Detect USB MIDI device connection and disconnection through Windows device
  notifications.
- Safely stop realtime input conversion when the active MIDI device is
  disconnected.
- Refresh the device list after reconnection without automatically restarting
  input reception.
- Added `Other > Send Bug Report / Suggestion`.
- Submit a bug report or suggestion with a subject, details, and optional
  reply-to address from the app.
- Added Japanese, English, and Simplified Chinese feedback forms.
- Show submission progress and a reference number after successful receipt.
- Show separate guidance for connection errors, timeouts, duplicate reports,
  and send limits.

[v1.7.2]

v1.7.2

This maintenance release improves the visual distinction of unused keyboard
ranges.

[Main changes]

- Unused keys outside the selected MIDI's final output range now use a solid
  black diagonal hatch.
- Removed the extra white range-boundary line from the keyboard.
- The hatch uses a cached pattern so it does not generate diagonal lines on
  every repaint.

[v1.7.1]

v1.7.1

This maintenance release improves slider operation and final-output-range
visibility.

[Main changes]

- Volume and playback-position sliders now center their handles at the clicked
  position while preserving stable handle dragging.
- Refined volume and playback slider handle shapes and scaling.
- Unified unused white and black key colors and added keyboard range boundaries
  that follow black-key shapes.
- Softened the unused-range display in the falling-note view and removed its
  extra boundary lines.
- Fine-tuned the current-track title position above the seek bar.

[v1.7.0]

v1.7.0

This release adds saved playlists and sequential MIDI playback.

[Main changes]

- Added a Playlist tab that shows each playlist and its tracks with name,
  duration, and playback status.
- Added a playlist editor. Create, rename, and delete playlists; drag songs
  from the MIDI list; reorder or remove tracks; and save the result.
- Play the selected playlist once from top to bottom and stop automatically
  after the final track.
- Wait for the configured countdown between playlist tracks. A countdown of
  0 seconds starts the next track immediately.
- Save playlists in playlists.json beside the application and remember the
  playlist-list pane width.

[v1.6.1]

v1.6.1

This UI fix release refines the player controls and current-track display.

[Main changes]

- Reorganized and enlarged the player transport controls for clearer operation.
- Replaced the volume knob with a horizontal slider and added one-click
  mute/unmute.
- Improved the speed, transpose, and octave-shift knobs, including reliable
  double-click reset and faster tooltips.
- Added a fixed current-track display above the seek bar. MIDI filename
  extensions are omitted from this display.
- Adjusted player spacing and sizing across UI scale settings.

[v1.6.0]

v1.6.0

This release improves performance visualization by assigning clear colors to
each track/channel source and restores chord revoicing without melody-source
priority.

[Main changes]

- Keyboard and falling-note displays now use distinct colors for each
  track/channel source. The corresponding track/channel buttons use the same
  colors.
- Removed the previous melody-source detection and highlighting so visual
  identity is based consistently on the actual track/channel source.
- Restored Chord revoicing for MIDI-file keyboard conversion and MIDI sound
  playback without automatically prioritizing a detected melody source.
- Simplified timing-judgment effects by removing radial lines and particles
  while retaining note-based visual feedback.
- Added an internal, versioned piano-arrangement analysis and cache foundation.
  Its controls remain disabled in this release while the beta workflow is
  finalized.

[v1.5.0]

v1.5.0

This release separates the GUI, software synthesizer, and MIDI parser into
multiple processes to distribute processing load and improve UI responsiveness
and audio-output stability. MIDI library management, performance visualization,
and update handling are also improved.

[Main changes]

- The GUI, software synth/PCM output, and MIDI parsing now run in three
  separate processes. Heavy MIDI analysis and waveform generation are less
  likely to block UI processing directly.
- Audio and MIDI-parser child processes are managed with a Windows Job Object
  and parent-process watchdog so they terminate with the main application.
- Qt audio queue and internal Buffer values can now be selected from the menu
  bar. The defaults are Qt 1024 and Buffer 512.
- MIDI files are now loaded recursively from the selected folder and all
  subfolders. The MIDI list shows the folder hierarchy and saves adjusted
  column widths.
- Reloading reuses unchanged MIDI metadata and updates only added, removed,
  or modified files.
- The selected MIDI's final output range is shown on the keyboard and
  falling-note display.
- Play sound now works with both MIDI input conversion and realtime input
  conversion while keyboard output remains enabled.
- Keyboard output is suppressed while this app or one of its child windows
  has focus.
- Removed the log tab, score, and combo display while keeping timing
  judgments and their visual effects.
- Reduced unnecessary playback planning, list rebuilding, visual updates,
  and idle audio processing.
- In-app updates now use separate supervisor and worker processes. A stalled
  or failed update is stopped, rolled back from backup, and cleaned up before
  the app restarts.
- The default countdown is now 0 seconds.

[v1.4.0]

v1.4.0

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
performance visualization, and automatic sustain generation.

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
    "ja": """v1.8.0

本バージョンでは、USB MIDI機器の抜き差し対応を改善し、
アプリ内から不具合や要望を送信できる機能を追加しました。

【主な変更】

- USB MIDI機器の接続・切断をWindowsの通知から検知します。
- 使用中のMIDI機器が切断された場合、リアルタイム入力変換を
  安全に停止します。
- MIDI機器を再接続した際にデバイス一覧を更新します。
  入力受付は自動再開しません。
- `その他 > 不具合・要望を送る`を追加しました。
- 不具合／要望、件名、詳細、任意の返信先をアプリ内から送信できます。
- 日本語、英語、簡体中文の送信画面に対応しました。
- 送信状況を表示し、受付完了後に受付番号を表示します。
- 通信エラー、タイムアウト、重複送信、送信回数制限を
  個別に案内します。

【v1.7.2】

v1.7.2

本バージョンは、選択中MIDIの未使用鍵盤を見分けやすくする
UIメンテナンスリリースです。

【主な変更】

- 最終出力音域外の未使用鍵盤を、不透明な黒地の斜線表示へ変更しました。
- 鍵盤へ追加していた白い音域境界線を削除しました。
- 斜線はキャッシュしたパターンを再利用し、再描画ごとの線生成を
  行わない構成にしました。

【v1.7.1】

v1.7.1

本バージョンは、スライダー操作と最終出力音域の視認性を改善する
メンテナンスリリースです。

【主な変更】

- 音量バーと再生位置バーをクリックした位置へ、つまみの中心が正確に
  移動するようにし、つまみのドラッグ操作も安定させました。
- 音量バーと再生位置バーのつまみ形状、および拡大時の表示を調整しました。
- 未使用の白鍵と黒鍵の色を統一し、黒鍵の形状に沿う使用音域の境界を
  鍵盤へ追加しました。
- 音ゲー欄の未使用音域表示を控えめにし、余分な境界線を削除しました。
- 再生バー上の曲名表示位置を微調整しました。

【v1.7.0】

v1.7.0

本バージョンでは、保存可能なプレイリストとMIDIの順次再生を追加しました。

【主な変更】

- プレイリスト一覧と、曲名、長さ、状態を表示するプレイリストタブを
  追加しました。
- プレイリストの新規作成、名前変更、削除、MIDI一覧からのドラッグ追加、
  曲順変更、曲の削除、保存に対応しました。
- 選択したプレイリストを上から1回だけ順番に再生し、最終曲の終了後に
  自動停止します。
- 曲間は設定中のカウントダウン秒数だけ待機します。0秒の場合は
  待機せず次の曲を開始します。
- プレイリストをアプリと同じ場所のplaylists.jsonへ保存し、
  プレイリスト一覧の表示幅も保持します。

【v1.6.1】

v1.6.1

本バージョンは、プレイヤー操作部と再生中曲名表示を改善するUI修正版です。

【主な変更】

- プレイヤーの再生操作ボタンを整理し、視認性と操作性を改善しました。
- 音量ノブを横スライダーへ変更し、ワンクリックのミュート／解除を
  追加しました。
- 速度、トランスポーズ、オクターブシフトのノブ操作を改善し、
  ダブルクリックによる初期値復帰とツールチップ表示を安定させました。
- 再生バー上に現在の曲名を固定表示し、MIDIファイルの拡張子は
  表示しないようにしました。
- 拡大率を変更した場合を含め、プレイヤー内の間隔とサイズを調整しました。

【v1.6.0】

v1.6.0

本バージョンでは、トラック／チャンネルごとの色分けによって演奏表示を
分かりやすくし、メロディー判定へ依存しない和音の再配置を復活しました。

【主な変更】

- 鍵盤と音ゲー欄をトラック／チャンネルごとの異なる色で表示し、
  対応するトラック／チャンネルボタンにも同じ色を表示します。
- 従来のメロディー判定と強調表示を削除し、実際のトラック／チャンネルを
  基準に一貫した色分けを行うようにしました。
- MIDIファイル入力変換とMIDI音源再生へ、メロディーを自動優先しない
  「和音の再配置」を復活しました。
- タイミング判定時の放射状の線と粒子を削除し、ノーツを基準とした
  視覚フィードバックへ整理しました。
- バージョン管理されたピアノ編曲解析とキャッシュの内部基盤を追加しました。
  解析βの操作画面は調整中のため、本バージョンでは無効です。

【v1.5.0】

v1.5.0

本バージョンでは、GUI、ソフトウェア音源、MIDI解析を
マルチプロセス化し、処理負荷の分散、操作応答性、
音声出力の安定性を改善しました。
MIDIライブラリ管理、演奏表示、更新処理も強化しています。

【主な変更】

- GUI、ソフトウェア音源／PCM出力、MIDI解析を
  3つのプロセスへ分離しました。
  重いMIDI解析や波形生成がGUI処理を直接占有しにくくなります。
- 音声プロセスとMIDI解析プロセスをWindows Job Objectと
  親プロセス監視で管理し、アプリ本体の終了時に
  子プロセスが残らないようにしました。
- Qtの音声待機量と内部Bufferをメニューバーから
  選択できるようにしました。初期値はQt 1024／Buffer 512です。
- 選択フォルダ配下のサブフォルダを再帰的に読み込み、
  MIDI一覧へフォルダ階層を表示するようにしました。
  列幅の変更と保存にも対応しました。
- リロード時は変更のないMIDI情報を再利用し、
  追加、削除、更新されたファイルだけを処理します。
- 選択中MIDIの最終出力音域を鍵盤と音ゲー欄へ表示します。
- MIDI入力変換とリアルタイム入力変換の両方で、
  キー入力と同時に「音を鳴らす」を利用できるようにしました。
- 本アプリまたは子ウィンドウがフォーカス中は、
  本アプリからのキー入力送信を抑止します。
- ログタブ、スコア、コンボ表示を削除し、
  タイミング判定と演出だけを残しました。
- 不要な再生計画、一覧再構築、描画更新、
  未使用時の音声処理を削減しました。
- アプリ内更新を監視プロセスと更新プロセスへ分離しました。
  進捗停止や異常終了を検出した場合は更新処理を終了し、
  バックアップから旧版を復元して一時ファイルを削除します。
- カウントダウンの初期値を0秒へ変更しました。

【v1.4.0】

v1.4.0

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
演奏の可視化、サスティンの自動生成を追加しました。

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
    "zh": """v1.8.0

本版本改进了USB MIDI设备的热插拔处理，并新增应用内问题报告与建议提交功能。

【主要变更】

- 通过Windows设备通知检测USB MIDI设备的连接与断开。
- 当前使用的MIDI设备断开时，会安全停止实时输入转换。
- MIDI设备重新连接后会刷新设备列表，但不会自动重新开始接收输入。
- 新增`其他 > 发送问题报告或建议`。
- 可在应用内提交问题／建议、主题、详细内容及可选回复方式。
- 提交界面支持日语、英语和简体中文。
- 显示提交进度，并在成功接收后显示受理编号。
- 分别提示连接错误、超时、重复提交和发送次数限制。

【v1.7.2】

v1.7.2

本版本是界面维护更新，改进了所选MIDI未使用键盘区域的辨识度。

【主要变更】

- 最终输出音域之外的未使用琴键改为不透明黑底斜线显示。
- 删除此前添加在键盘上的白色音域边界线。
- 斜线使用缓存图案，避免每次重绘时重新生成线条。

【v1.7.1】

v1.7.1

本版本是维护更新，改进了滑块操作和最终输出音域的可见性。

【主要变更】

- 点击音量和播放位置滑块时，滑块中心会准确移动到点击位置，同时保持
  拖动操作稳定。
- 调整音量和播放位置滑块的形状及缩放显示。
- 统一未使用白键与黑键的颜色，并在键盘上添加沿黑键形状绘制的音域边界。
- 减弱下落音符区域的未使用音域显示，并删除多余边界线。
- 微调进度条上方的当前曲目名称位置。

【v1.7.0】

v1.7.0

本版本新增了可保存的播放列表和MIDI顺序播放功能。

【主要变更】

- 新增播放列表标签页，显示播放列表及其中曲目的名称、时长和播放状态。
- 新增播放列表编辑器，可新建、重命名和删除播放列表，从MIDI列表拖入曲目，
  调整顺序、移除曲目并保存。
- 所选播放列表会从上到下播放一次，并在最后一首结束后自动停止。
- 曲目之间按照当前倒计时秒数等待；设为0秒时会立即播放下一首。
- 播放列表保存在应用程序旁的playlists.json中，并保存播放列表窗格宽度。

【v1.6.1】

v1.6.1

本版本是界面修正版，改进了播放器控制区和当前曲目显示。

【主要变更】

- 重新整理并放大播放器控制按钮，提高可见性和操作性。
- 将音量旋钮改为横向滑块，并添加一键静音／取消静音。
- 改进速度、移调和八度移位旋钮，包括稳定的双击复位和更快的工具提示。
- 在进度条上方固定显示当前曲目名称，并隐藏MIDI文件扩展名。
- 调整不同界面缩放比例下播放器内部的间距和尺寸。

【v1.6.0】

v1.6.0

本版本通过为每个音轨／通道分配不同颜色，使演奏显示更容易识别，
并恢复了不依赖旋律来源优先级的和弦重排功能。

【主要变更】

- 键盘和下落音符显示会按音轨／通道使用不同颜色，对应的音轨／通道按钮
  也会显示相同颜色。
- 删除旧的旋律来源检测和强调显示，统一按实际音轨／通道进行颜色区分。
- 恢复用于MIDI文件键盘转换和MIDI声音播放的和弦重排，
  不再自动优先检测到的旋律来源。
- 删除节奏判定时的放射线和粒子效果，保留以音符为基础的视觉反馈。
- 添加带版本管理的钢琴编曲分析与缓存内部基础。
  解析β界面仍在调整中，因此本版本暂时不可操作。

【v1.5.0】

v1.5.0

本版本将界面、软件合成器和MIDI解析分离到多个进程中，
以分担处理负载并改善界面响应和音频输出稳定性。
同时还加强了MIDI文件管理、演奏显示和更新处理。

【主要变更】

- 界面、软件合成器／PCM输出和MIDI解析现在分别运行在
  三个进程中，较重的MIDI分析与波形生成不易直接阻塞界面处理。
- 音频进程与MIDI解析进程由Windows Job Object和父进程监控管理，
  并随主程序退出，避免子进程残留。
- 可从菜单栏选择Qt音频等待量和内部Buffer，
  默认值为Qt 1024／Buffer 512。
- 递归读取所选文件夹及其所有子文件夹中的MIDI文件，
  并在列表中显示文件夹层级，同时保存调整后的列宽。
- 重新加载时复用未变更的MIDI信息，仅处理新增、删除或修改的文件。
- 在键盘和下落音符画面中显示所选MIDI的最终输出音域。
- MIDI输入转换和实时输入转换均可在发送按键的同时播放声音。
- 当本应用或其子窗口获得焦点时，不发送键盘输入。
- 删除日志标签页、分数和连击显示，保留时序判定及其视觉效果。
- 减少不必要的播放规划、列表重建、绘制更新和空闲音频处理。
- 应用内更新改为监控进程与更新进程分离。
  检测到更新停滞或异常退出时，会终止更新、从备份恢复并删除临时文件。
- 默认倒计时改为0秒。

【v1.4.0】

v1.4.0

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
演奏可视化，以及自动延音生成功能。

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
        "send_feedback": "Send Bug Report / Suggestion",
        "feedback_title": "Send Bug Report / Suggestion",
        "feedback_intro": (
            "Tell us what happened or what would make the app better."
        ),
        "feedback_kind": "Type",
        "feedback_bug": "Bug",
        "feedback_improvement": "Suggestion",
        "feedback_subject": "Subject",
        "feedback_subject_placeholder": "Brief summary",
        "feedback_message": "Details",
        "feedback_message_placeholder": (
            "For bugs, include the steps and what you expected to happen."
        ),
        "feedback_contact": "Reply-to (optional)",
        "feedback_contact_placeholder": "Email address or other contact",
        "feedback_send": "Send",
        "feedback_sending": "Sending...",
        "feedback_progress": "Send progress",
        "feedback_success_title": "Sent",
        "feedback_success": (
            "Thank you. Your message has been received.\n"
            "Reference: {reference}"
        ),
        "feedback_error_title": "Could not send",
        "feedback_validation": (
            "Enter a subject of at least 3 characters and details of at "
            "least 10 characters."
        ),
        "feedback_error_duplicate": (
            "The same message has already been received."
        ),
        "feedback_error_rate_limited": (
            "The send limit has been reached. Try again in about "
            "{minutes} minutes."
        ),
        "feedback_error_network": (
            "Could not connect to the server. Check your internet connection."
        ),
        "feedback_error_timeout": (
            "The server did not respond in time. Please try again later."
        ),
        "feedback_error_server": (
            "The server could not receive the message. Please try again later."
        ),
        "feedback_error_unavailable": (
            "The feedback service is not configured in this build."
        ),
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
        "use_piano_arrangement": "Use analysis",
        "arrangement_quality": "Arrangement quality",
        "arrangement_quality_beta": "Analysis \u03b2",
        "analyze_arrangement": "Analyze",
        "cancel_arrangement": "Cancel {percent}%",
        "arrangement_cached": "Analyzed",
        "arrangement_title": "Piano Solo Analysis",
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
        "conversion_sound": "Play sound",
        "countdown": "Countdown",
        "seconds_unit": "sec",
        "countdown_sound": "Sound",
        "game_countdown_sound": "Play sound in game (ensemble)",
        "humanize_timing": "Timing variation",
        "chord_optimization": "Chord revoicing",
        "optimization_progress": "Optimizing {percent}%",
        "chord_strum": "Chord spread",
        "auto_sustain": "Automatic sustain generation",
        "repeat_prevention": "Prevent rapid repeats",
        "playback_speed": "Speed",
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
        "midi_sound_volume": "Volume",
        "mute": "Mute",
        "unmute": "Unmute",
        "previous_track": "Previous track",
        "play_sound": "Play",
        "pause_sound": "Pause",
        "next_track": "Next track",
        "playback_mode_off": "Continuous playback off",
        "playback_mode_continuous": "Continuous playback",
        "playback_mode_repeat_one": "Repeat one",
        "playlist": "Playlist",
        "playlist_editor": "Playlist Editor",
        "playlist_names": "Playlists",
        "playlist_name": "Playlist name",
        "playlist_total_duration": "Total duration: {duration}",
        "status": "Status",
        "playlist_status_playing": "Playing",
        "playlist_status_waiting": "Waiting",
        "playlist_status_played": "Played",
        "playlist_status_missing": "File missing",
        "playlist_drop_hint": "Drag MIDI songs here",
        "playlist_new_title": "New playlist",
        "playlist_rename_title": "Rename playlist",
        "playlist_delete_title": "Delete playlist",
        "playlist_delete_confirm": 'Delete "{name}"?',
        "playlist_create_first": "Create or select a playlist first.",
        "playlist_select_first": "Select a playlist first.",
        "playlist_empty": "The selected playlist has no songs.",
        "playlist_save_failed_title": "Playlist save failed",
        "playlist_unsaved_title": "Unsaved playlist",
        "playlist_unsaved_message": "Save the playlist changes?",
        "new": "New",
        "rename": "Rename",
        "delete": "Delete",
        "remove": "Remove",
        "move_up": "Move up",
        "move_down": "Move down",
        "save": "Save",
        "discard": "Discard",
        "cancel": "Cancel",
        "midi_list": "MIDI List",
        "name": "Name",
        "folder": "Folder",
        "duration": "Duration",
        "no_midi_files": "No MIDI files were found in the selected folder.",
        "select_midi_file": "Select MIDI folder",
        "load_failed_title": "Load failed",
        "playback_failed_title": "Playback failed",
        "no_midi_title": "No MIDI",
        "load_midi_first": "Load a MIDI file first.",
        "no_events_title": "No events",
        "no_events_enabled": "No events are enabled for playback.",
        "already_playing_title": "Already playing",
        "waiting": "waiting..",
        "none": "none",
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
        "send_feedback": "\u4e0d\u5177\u5408\u30fb\u8981\u671b\u3092\u9001\u308b",
        "feedback_title": "\u4e0d\u5177\u5408\u30fb\u8981\u671b\u3092\u9001\u308b",
        "feedback_intro": (
            "\u767a\u751f\u3057\u305f\u554f\u984c\u3084\u3001\u30a2\u30d7\u30ea\u3092\u3088\u308a\u826f\u304f\u3059\u308b\u305f\u3081\u306e"
            "\u3054\u610f\u898b\u3092\u304a\u805e\u304b\u305b\u304f\u3060\u3055\u3044\u3002"
        ),
        "feedback_kind": "\u7a2e\u5225",
        "feedback_bug": "\u4e0d\u5177\u5408",
        "feedback_improvement": "\u8981\u671b",
        "feedback_subject": "\u4ef6\u540d",
        "feedback_subject_placeholder": "\u5185\u5bb9\u3092\u7c21\u6f54\u306b\u5165\u529b",
        "feedback_message": "\u8a73\u7d30",
        "feedback_message_placeholder": (
            "\u4e0d\u5177\u5408\u306e\u5834\u5408\u306f\u3001\u64cd\u4f5c\u624b\u9806\u3068\u671f\u5f85\u3057\u305f\u7d50\u679c\u3082\u3054\u8a18\u5165\u304f\u3060\u3055\u3044\u3002"
        ),
        "feedback_contact": "\u8fd4\u4fe1\u5148\uff08\u4efb\u610f\uff09",
        "feedback_contact_placeholder": "\u30e1\u30fc\u30eb\u30a2\u30c9\u30ec\u30b9\u306a\u3069",
        "feedback_send": "\u9001\u4fe1",
        "feedback_sending": "\u9001\u4fe1\u4e2d...",
        "feedback_progress": "\u9001\u4fe1\u72b6\u6cc1",
        "feedback_success_title": "\u9001\u4fe1\u5b8c\u4e86",
        "feedback_success": (
            "\u3054\u9023\u7d61\u3092\u53d7\u3051\u4ed8\u3051\u307e\u3057\u305f\u3002\u3042\u308a\u304c\u3068\u3046\u3054\u3056\u3044\u307e\u3059\u3002\n"
            "\u53d7\u4ed8\u756a\u53f7: {reference}"
        ),
        "feedback_error_title": "\u9001\u4fe1\u3067\u304d\u307e\u305b\u3093",
        "feedback_validation": (
            "\u4ef6\u540d\u306f3\u6587\u5b57\u4ee5\u4e0a\u3001\u8a73\u7d30\u306f10\u6587\u5b57\u4ee5\u4e0a\u3067\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        ),
        "feedback_error_duplicate": (
            "\u540c\u3058\u5185\u5bb9\u306f\u3059\u3067\u306b\u53d7\u3051\u4ed8\u3051\u3066\u3044\u307e\u3059\u3002"
        ),
        "feedback_error_rate_limited": (
            "\u9001\u4fe1\u56de\u6570\u304c\u4e0a\u9650\u306b\u9054\u3057\u307e\u3057\u305f\u3002"
            "\u7d04{minutes}\u5206\u5f8c\u306b\u3082\u3046\u4e00\u5ea6\u304a\u8a66\u3057\u304f\u3060\u3055\u3044\u3002"
        ),
        "feedback_error_network": (
            "\u30b5\u30fc\u30d0\u306b\u63a5\u7d9a\u3067\u304d\u307e\u305b\u3093\u3002\u30a4\u30f3\u30bf\u30fc\u30cd\u30c3\u30c8\u63a5\u7d9a\u3092\u3054\u78ba\u8a8d\u304f\u3060\u3055\u3044\u3002"
        ),
        "feedback_error_timeout": (
            "\u30b5\u30fc\u30d0\u304b\u3089\u5fdc\u7b54\u304c\u3042\u308a\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u6642\u9593\u3092\u304a\u3044\u3066\u304a\u8a66\u3057\u304f\u3060\u3055\u3044\u3002"
        ),
        "feedback_error_server": (
            "\u30b5\u30fc\u30d0\u304c\u53d7\u4ed8\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u6642\u9593\u3092\u304a\u3044\u3066\u304a\u8a66\u3057\u304f\u3060\u3055\u3044\u3002"
        ),
        "feedback_error_unavailable": (
            "\u3053\u306e\u30d3\u30eb\u30c9\u306b\u306f\u9001\u4fe1\u5148\u304c\u8a2d\u5b9a\u3055\u308c\u3066\u3044\u307e\u305b\u3093\u3002"
        ),
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
        "use_piano_arrangement": "\u89e3\u6790\u3092\u4f7f\u3046",
        "arrangement_quality": "\u7de8\u66f2\u54c1\u8cea",
        "arrangement_quality_beta": "\u89e3\u6790\u03b2",
        "analyze_arrangement": "\u89e3\u6790",
        "cancel_arrangement": "\u4e2d\u6b62 {percent}%",
        "arrangement_cached": "\u89e3\u6790\u6e08\u307f",
        "arrangement_title": "\u30d4\u30a2\u30ce\u30bd\u30ed\u89e3\u6790",
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
        "conversion_sound": "\u97f3\u3092\u9cf4\u3089\u3059",
        "countdown": "\u30ab\u30a6\u30f3\u30c8\u30c0\u30a6\u30f3",
        "seconds_unit": "\u79d2",
        "countdown_sound": "\u97f3\u3092\u9cf4\u3089\u3059",
        "game_countdown_sound": "\u30b2\u30fc\u30e0\u5185\u3067\u97f3\u3092\u9cf4\u3089\u3059(\u5408\u594f\u7528)",
        "humanize_timing": "\u30bf\u30a4\u30df\u30f3\u30b0\u306e\u5206\u6563",
        "chord_optimization": "\u548c\u97f3\u306e\u518d\u914d\u7f6e",
        "optimization_progress": "\u6700\u9069\u5316\u4e2d {percent}%",
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
        "mute": "\u30df\u30e5\u30fc\u30c8",
        "unmute": "\u30df\u30e5\u30fc\u30c8\u89e3\u9664",
        "previous_track": "\u524d\u306e\u66f2",
        "play_sound": "\u518d\u751f",
        "pause_sound": "\u4e00\u6642\u505c\u6b62",
        "next_track": "\u6b21\u306e\u66f2",
        "playback_mode_off": "\u9023\u7d9a\u518d\u751f\u30aa\u30d5",
        "playback_mode_continuous": "\u9023\u7d9a\u518d\u751f",
        "playback_mode_repeat_one": "1\u66f2\u30eb\u30fc\u30d7\u518d\u751f",
        "playlist": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8",
        "playlist_editor": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u7de8\u96c6",
        "playlist_names": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u4e00\u89a7",
        "playlist_name": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u540d",
        "playlist_total_duration": "\u5408\u8a08\u6642\u9593: {duration}",
        "status": "\u72b6\u614b",
        "playlist_status_playing": "\u5b9f\u884c\u4e2d",
        "playlist_status_waiting": "\u30ad\u30e5\u30fc\u30a4\u30f3\u30b0",
        "playlist_status_played": "\u5b8c\u4e86",
        "playlist_status_missing": "\u30d5\u30a1\u30a4\u30eb\u306a\u3057",
        "playlist_drop_hint": "MIDI\u4e00\u89a7\u304b\u3089\u66f2\u3092\u30c9\u30e9\u30c3\u30b0",
        "playlist_new_title": "\u65b0\u898f\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8",
        "playlist_rename_title": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u540d\u3092\u5909\u66f4",
        "playlist_delete_title": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u3092\u524a\u9664",
        "playlist_delete_confirm": "\u300c{name}\u300d\u3092\u524a\u9664\u3057\u307e\u3059\u304b\uff1f",
        "playlist_create_first": "\u5148\u306b\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u3092\u4f5c\u6210\u307e\u305f\u306f\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
        "playlist_select_first": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u3092\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
        "playlist_empty": "\u9078\u629e\u3057\u305f\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u306b\u66f2\u304c\u3042\u308a\u307e\u305b\u3093\u3002",
        "playlist_save_failed_title": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u4fdd\u5b58\u5931\u6557",
        "playlist_unsaved_title": "\u672a\u4fdd\u5b58\u306e\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8",
        "playlist_unsaved_message": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8\u306e\u5909\u66f4\u3092\u4fdd\u5b58\u3057\u307e\u3059\u304b\uff1f",
        "new": "\u65b0\u898f",
        "rename": "\u540d\u524d\u5909\u66f4",
        "delete": "\u524a\u9664",
        "remove": "\u66f2\u3092\u524a\u9664",
        "move_up": "\u4e0a\u3078",
        "move_down": "\u4e0b\u3078",
        "save": "\u4fdd\u5b58",
        "discard": "\u4fdd\u5b58\u3057\u306a\u3044",
        "cancel": "\u30ad\u30e3\u30f3\u30bb\u30eb",
        "midi_list": "MIDI\u4e00\u89a7",
        "name": "\u540d\u524d",
        "folder": "\u30d5\u30a9\u30eb\u30c0",
        "duration": "\u9577\u3055",
        "no_midi_files": "\u9078\u629e\u3057\u305f\u30d5\u30a9\u30eb\u30c0\u306bMIDI\u30d5\u30a1\u30a4\u30eb\u304c\u3042\u308a\u307e\u305b\u3093\u3002",
        "select_midi_file": "MIDI\u30d5\u30a9\u30eb\u30c0\u3092\u9078\u629e",
        "load_failed_title": "\u8aad\u307f\u8fbc\u307f\u5931\u6557",
        "playback_failed_title": "\u518d\u751f\u5931\u6557",
        "no_midi_title": "MIDI\u672a\u9078\u629e",
        "load_midi_first": "\u5148\u306bMIDI\u30d5\u30a1\u30a4\u30eb\u3092\u8aad\u307f\u8fbc\u3093\u3067\u304f\u3060\u3055\u3044\u3002",
        "no_events_title": "\u30a4\u30d9\u30f3\u30c8\u306a\u3057",
        "no_events_enabled": "\u518d\u751f\u5bfe\u8c61\u306e\u30a4\u30d9\u30f3\u30c8\u304c\u3042\u308a\u307e\u305b\u3093\u3002",
        "already_playing_title": "\u518d\u751f\u4e2d",
        "waiting": "waiting..",
        "none": "\u306a\u3057",
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
        "send_feedback": "\u53d1\u9001\u95ee\u9898\u62a5\u544a\u6216\u5efa\u8bae",
        "feedback_title": "\u53d1\u9001\u95ee\u9898\u62a5\u544a\u6216\u5efa\u8bae",
        "feedback_intro": (
            "\u8bf7\u544a\u8bc9\u6211\u4eec\u9047\u5230\u7684\u95ee\u9898\uff0c\u6216\u53ef\u4ee5\u6539\u8fdb\u5e94\u7528\u7684\u5efa\u8bae\u3002"
        ),
        "feedback_kind": "\u7c7b\u578b",
        "feedback_bug": "\u95ee\u9898",
        "feedback_improvement": "\u5efa\u8bae",
        "feedback_subject": "\u4e3b\u9898",
        "feedback_subject_placeholder": "\u7b80\u8981\u8bf4\u660e\u5185\u5bb9",
        "feedback_message": "\u8be6\u7ec6\u5185\u5bb9",
        "feedback_message_placeholder": (
            "\u5982\u679c\u662f\u95ee\u9898\uff0c\u8bf7\u5199\u660e\u64cd\u4f5c\u6b65\u9aa4\u548c\u9884\u671f\u7ed3\u679c\u3002"
        ),
        "feedback_contact": "\u56de\u590d\u65b9\u5f0f\uff08\u53ef\u9009\uff09",
        "feedback_contact_placeholder": "\u7535\u5b50\u90ae\u4ef6\u6216\u5176\u4ed6\u8054\u7cfb\u65b9\u5f0f",
        "feedback_send": "\u53d1\u9001",
        "feedback_sending": "\u53d1\u9001\u4e2d...",
        "feedback_progress": "\u53d1\u9001\u8fdb\u5ea6",
        "feedback_success_title": "\u53d1\u9001\u5b8c\u6210",
        "feedback_success": (
            "\u611f\u8c22\u60a8\u7684\u53cd\u9988\uff0c\u6211\u4eec\u5df2\u6536\u5230\u3002\n"
            "\u7f16\u53f7: {reference}"
        ),
        "feedback_error_title": "\u65e0\u6cd5\u53d1\u9001",
        "feedback_validation": (
            "\u4e3b\u9898\u81f3\u5c11\u8f93\u51653\u4e2a\u5b57\u7b26\uff0c\u8be6\u7ec6\u5185\u5bb9\u81f3\u5c11\u8f93\u516510\u4e2a\u5b57\u7b26\u3002"
        ),
        "feedback_error_duplicate": "\u76f8\u540c\u5185\u5bb9\u5df2\u7ecf\u63a5\u6536\u3002",
        "feedback_error_rate_limited": (
            "\u5df2\u8fbe\u5230\u53d1\u9001\u6b21\u6570\u4e0a\u9650\u3002\u8bf7\u5927\u7ea6{minutes}\u5206\u949f\u540e\u518d\u8bd5\u3002"
        ),
        "feedback_error_network": (
            "\u65e0\u6cd5\u8fde\u63a5\u670d\u52a1\u5668\u3002\u8bf7\u68c0\u67e5\u7f51\u7edc\u8fde\u63a5\u3002"
        ),
        "feedback_error_timeout": (
            "\u670d\u52a1\u5668\u672a\u53ca\u65f6\u54cd\u5e94\u3002\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002"
        ),
        "feedback_error_server": (
            "\u670d\u52a1\u5668\u65e0\u6cd5\u63a5\u6536\u6b64\u5185\u5bb9\u3002\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002"
        ),
        "feedback_error_unavailable": (
            "\u6b64\u7248\u672c\u5c1a\u672a\u8bbe\u7f6e\u53cd\u9988\u670d\u52a1\u3002"
        ),
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
        "use_piano_arrangement": "\u4f7f\u7528\u5206\u6790",
        "arrangement_quality": "\u7f16\u66f2\u8d28\u91cf",
        "arrangement_quality_beta": "\u89e3\u6790\u03b2",
        "analyze_arrangement": "\u5206\u6790",
        "cancel_arrangement": "\u53d6\u6d88 {percent}%",
        "arrangement_cached": "\u5df2\u5206\u6790",
        "arrangement_title": "\u94a2\u7434\u72ec\u594f\u5206\u6790",
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
        "conversion_sound": "\u64ad\u653e\u58f0\u97f3",
        "countdown": "\u5012\u8ba1\u65f6",
        "seconds_unit": "\u79d2",
        "countdown_sound": "\u64ad\u653e\u58f0\u97f3",
        "game_countdown_sound": "\u5728\u6e38\u620f\u5185\u64ad\u653e\u58f0\u97f3(\u5408\u594f\u7528)",
        "humanize_timing": "\u65f6\u5e8f\u5206\u6563",
        "chord_optimization": "\u548c\u5f26\u91cd\u6392",
        "optimization_progress": "\u4f18\u5316\u4e2d {percent}%",
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
        "mute": "\u9759\u97f3",
        "unmute": "\u53d6\u6d88\u9759\u97f3",
        "previous_track": "\u4e0a\u4e00\u9996",
        "play_sound": "\u64ad\u653e",
        "pause_sound": "\u6682\u505c",
        "next_track": "\u4e0b\u4e00\u9996",
        "playback_mode_off": "\u5173\u95ed\u8fde\u7eed\u64ad\u653e",
        "playback_mode_continuous": "\u8fde\u7eed\u64ad\u653e",
        "playback_mode_repeat_one": "\u5355\u66f2\u5faa\u73af",
        "playlist": "\u64ad\u653e\u5217\u8868",
        "playlist_editor": "\u7f16\u8f91\u64ad\u653e\u5217\u8868",
        "playlist_names": "\u64ad\u653e\u5217\u8868",
        "playlist_name": "\u64ad\u653e\u5217\u8868\u540d\u79f0",
        "playlist_total_duration": "\u66f2\u76ee\u603b\u65f6\u957f: {duration}",
        "status": "\u72b6\u6001",
        "playlist_status_playing": "\u64ad\u653e\u4e2d",
        "playlist_status_waiting": "\u7b49\u5f85\u4e2d",
        "playlist_status_played": "\u5df2\u64ad\u653e",
        "playlist_status_missing": "\u6587\u4ef6\u4e22\u5931",
        "playlist_drop_hint": "\u4ece MIDI \u5217\u8868\u62d6\u653e\u66f2\u76ee",
        "playlist_new_title": "\u65b0\u5efa\u64ad\u653e\u5217\u8868",
        "playlist_rename_title": "\u91cd\u547d\u540d\u64ad\u653e\u5217\u8868",
        "playlist_delete_title": "\u5220\u9664\u64ad\u653e\u5217\u8868",
        "playlist_delete_confirm": "\u662f\u5426\u5220\u9664\u201c{name}\u201d\uff1f",
        "playlist_create_first": "\u8bf7\u5148\u521b\u5efa\u6216\u9009\u62e9\u64ad\u653e\u5217\u8868\u3002",
        "playlist_select_first": "\u8bf7\u5148\u9009\u62e9\u64ad\u653e\u5217\u8868\u3002",
        "playlist_empty": "\u6240\u9009\u64ad\u653e\u5217\u8868\u4e2d\u6ca1\u6709\u66f2\u76ee\u3002",
        "playlist_save_failed_title": "\u64ad\u653e\u5217\u8868\u4fdd\u5b58\u5931\u8d25",
        "playlist_unsaved_title": "\u64ad\u653e\u5217\u8868\u672a\u4fdd\u5b58",
        "playlist_unsaved_message": "\u662f\u5426\u4fdd\u5b58\u64ad\u653e\u5217\u8868\u66f4\u6539\uff1f",
        "new": "\u65b0\u5efa",
        "rename": "\u91cd\u547d\u540d",
        "delete": "\u5220\u9664",
        "remove": "\u79fb\u9664\u66f2\u76ee",
        "move_up": "\u4e0a\u79fb",
        "move_down": "\u4e0b\u79fb",
        "save": "\u4fdd\u5b58",
        "discard": "\u4e0d\u4fdd\u5b58",
        "cancel": "\u53d6\u6d88",
        "midi_list": "MIDI \u5217\u8868",
        "name": "\u540d\u79f0",
        "folder": "\u6587\u4ef6\u5939",
        "duration": "\u65f6\u957f",
        "no_midi_files": "\u6240\u9009\u6587\u4ef6\u5939\u4e2d\u6ca1\u6709 MIDI \u6587\u4ef6\u3002",
        "select_midi_file": "\u9009\u62e9 MIDI \u6587\u4ef6\u5939",
        "load_failed_title": "\u52a0\u8f7d\u5931\u8d25",
        "playback_failed_title": "\u64ad\u653e\u5931\u8d25",
        "no_midi_title": "\u672a\u9009\u62e9 MIDI",
        "load_midi_first": "\u8bf7\u5148\u52a0\u8f7d MIDI \u6587\u4ef6\u3002",
        "no_events_title": "\u6ca1\u6709\u4e8b\u4ef6",
        "no_events_enabled": "\u6ca1\u6709\u542f\u7528\u53ef\u64ad\u653e\u7684\u4e8b\u4ef6\u3002",
        "already_playing_title": "\u6b63\u5728\u64ad\u653e",
        "waiting": "waiting..",
        "none": "\u65e0",
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
