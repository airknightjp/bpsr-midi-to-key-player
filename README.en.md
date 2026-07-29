# BPSR MIDI to KEY Player

[日本語](README.md) | [中文](README.zh-CN.md)

> **Multilingual UI:** Supports Japanese, English, and Chinese.

> **Multiprocess load distribution:** The GUI, software synthesizer, and MIDI parser run in three separate processes so heavy MIDI analysis and waveform generation are less likely to block UI interaction directly.

BPSR MIDI to KEY Player is a Windows desktop tool that converts MIDI files and USB MIDI keyboard input into keyboard events.

It is designed for BPSR-style keyboard performance. MIDI notes are mapped to ordinary keyboard keys and sent to the currently focused application. The app also supports MIDI sound playback, track/channel selection, realtime input conversion, note range adjustment, custom key bindings, global shortcuts, themes, and task tray storage.

## Distribution

This application is distributed as an installation-free extracted folder. Extract the entire release ZIP to any location, then launch `BPSR_MIDI_to_KEY_Player.exe` inside the `BPSR_MIDI_to_KEY_Player` folder.

The `_internal` folder contains files required by the application. Do not move the EXE by itself or delete files from the extracted folder.

## Features

- Recursively load `.mid` and `.midi` files from the selected folder and all subfolders.
- Show name, folder hierarchy, and duration in the MIDI list. Folder hierarchy uses the `Parent > Child > Grandchild` format.
- Reflect the selected MIDI's final output range on the keyboard and falling-note display with subdued unused-range colors. Keyboard boundaries follow the black-key shapes.
- Resize each MIDI-list column by dragging its header boundary and save the adjusted widths.
- Double-click a MIDI file to play or stop MIDI sound playback.
- Convert MIDI files into keyboard input.
- Convert realtime USB MIDI keyboard input into keyboard input.
- Enable `Play sound` to hear the conversion output while sending key input.
- Adjust the volume slider, mute state, playback position, and playback speed (10-200%). Double-click the speed knob to reset it to 100%.
- Adjust UI scale (100-200%) and window opacity from the View menu.
- Adjust transpose (-12 to +12 semitones) and octave shift (-3 to +3) above the player. Double-click either knob to reset it to 0.
- Optionally fit notes into the C3-B5 three-octave range.
- Handle notes outside C3-B5 with octave-switch keys when range fitting is disabled.
- Configure timing variation, chord spread, chord revoicing, and automatic sustain generation.
- Configure rapid-repeat prevention.
- Display used track/channel combinations as circular buttons in `11` format.
- Toggle each track/channel combination, with immediate changes during playback.
- Convert sustain pedal CC64 to the Space key.
- Select Piano, Electric Piano, Organ, or Synth as the software sound source.
- Run the GUI, software synth/PCM output, and MIDI parsing in separate processes to distribute processing load.
- Select the Qt audio queue and internal Buffer from the menu bar. Defaults are Qt 1024 and Buffer 512.
- Show final output notes on a full A0-C8 keyboard and falling-note rhythm display.
- Control Previous, Play/Pause, Next, Continuous playback, and Repeat one. The current track is shown above the seek bar without its filename extension.
- Create, rename, reorder, and save playlists by dragging songs from the MIDI list.
- Play a playlist once from top to bottom, wait for the configured countdown between tracks, and show each track's playback status.
- Configure a countdown before MIDI input conversion starts.
- Play countdown sound and optionally press the in-game C3 key for ensemble use.
- Configure global start, pause, and stop shortcuts by pressing keys. The defaults are F9, F10, and F11, and standalone function keys are supported. These shortcuts control MIDI input conversion only and do not affect realtime input conversion or MIDI sound playback.
- Lock shortcut settings to avoid accidental changes.
- Edit the C3-B5 bindings and the Sustain, Octave down, and Octave up keys from `Settings > Key Bindings`.
- Highlight duplicate key bindings in red.
- Restore all key bindings to their defaults.
- Switch UI language between Japanese, English, and Chinese.
- Choose from multiple color themes, including Sky Blue. Sky Blue is the default for new settings.
- Save always-on-top, window size including enlarged layouts, and the last loaded MIDI folder.
- Reorder the five main panels by drag and drop and show or hide them from the View menu.
- `Analysis beta` remains unavailable in v1.7.1 while its internal workflow is being finalized.
- Support `[Close] to tray`.
- Prevent duplicate instances.
- Check, download, verify, install, and restart updates through GitHub Releases.
- Show version, copyright, and GitHub link from `Other > About BPSR MIDI to KEY Player`.

## Menus

- `File > Select MIDI Folder`: Select a folder containing MIDI files.
- `File > Save Settings`: Save the current settings immediately.
- `File > Exit`: Fully exit the app.
- `View`: Change scale, opacity, always-on-top, and panel visibility.
- `Settings`: Change theme, language, key bindings, and tray behavior.
- `Other > Check for Updates`: Check GitHub Releases for the latest version.
- `Other > Release Notes`: Show the changes in the current version.
- `Other > About BPSR MIDI to KEY Player`: Show version information and the GitHub link.

## Software Updates

- At startup, the app checks GitHub Releases and notifies you only when an update is available.
- Automatic checks run at most once per hour. The last check time is stored in `settings.json`.
- Manual checks from `Other > Check for Updates` are always available.
- A confirmation is shown before updating, followed by one progress window for download, verification, installation, and restart.
- The release ZIP size, SHA-256 digest, archive structure, and path safety are verified before installation.
- The local `settings.json` is preserved. After a successful update, the app restarts automatically and returns to the foreground.
- If an update fails, the previous application files are restored and the error is reported on the next launch.
- A dedicated supervisor process monitors update progress. If the updater stalls or exits abnormally, it is stopped, the backup is restored, and temporary files are removed.
- No GitHub credentials or access tokens are included in the application.

## Software Synth and Audio Output

MIDI sound playback and realtime preview sound use an in-app software synthesizer without connecting to WinMM MIDI output.

- Select from Piano, Electric Piano, Organ, and Synth.
- Play up to 64 simultaneous voices.
- Prefer the output device's recommended audio format, with fallback to Float32, Int16, or Int32 when needed.
- Select the Qt audio queue and internal Buffer from menu-bar drop-downs to suit the current environment.
- The defaults are `Qt 1024` and `Buffer 512`. Selected values are saved to `settings.json`.
- The current values are shown as `Qt ... | Buffer ...` in the menu bar.

## Multiprocess Architecture

Normal operation is divided across three processes:

- **Main process:** Qt UI, settings, playback control, realtime MIDI input, key conversion, and SendInput.
- **Audio process:** Software synthesis, waveform generation, PCM buffer management, and Qt audio output.
- **MIDI parser process:** MIDI events, duration, tracks/channels, and note-range analysis.

Separating audio generation and MIDI parsing from the GUI prevents their heavier work from concentrating on the UI process during large-file analysis or multi-note playback. Child processes are managed with a Windows Job Object and parent-process watchdog so they terminate with the main application.

## Performance Display

- Show the final output notes from MIDI playback, MIDI input conversion, and realtime input conversion on a full A0-C8 keyboard.
- Display each note's start, duration, and release position in a falling-note lane aligned with the keyboard.
- Hiding the Rhythm Game or Keyboard panel stops its related drawing and calculations and resynchronizes it when shown again.

## Note Range

The base BPSR keyboard range is C3-B5.

- Notes in C3-B5 are played directly.
- Lower notes can be played by switching to the low octave range.
- Higher notes can be played by switching to the high octave range.
- When `Fit to 3 octaves` is enabled, notes outside C3-B5 are moved by octaves until they fit inside C3-B5.

Transpose and octave shift apply to MIDI file keyboard conversion, realtime input conversion, MIDI sound playback, and realtime preview sound. Range fitting or normal out-of-range handling is applied after the pitch shift.

## Chord Revoicing And Performance Timing

When `Chord revoicing` is enabled, notes starting within approximately 35 ms are analyzed as a chord and moved by octaves into a playable layout.

- The top voice, bass, common tones, voice order, and smooth movement between adjacent chords are considered while excessive spacing, physical-key collisions, and frequent range switches are discouraged.
- With `Fit to 3 octaves` enabled, the result stays inside C3-B5. Otherwise, low, normal, and high ranges are compared and range-switch keys are used only where needed.
- Available switching time is evaluated using the current playback speed, allowing a wider range at slower speeds and discouraging frequent switches at faster speeds.
- This applies to MIDI-file keyboard conversion and MIDI sound playback, not realtime input conversion.

`Timing variation` adds a small timing variation while keeping notes with the same original onset together.

`Chord spread` adds a short onset difference of up to 12 ms to two or more distinct notes starting at exactly the same time. Existing onset differences in the MIDI are preserved.

These options apply to MIDI-file keyboard conversion and MIDI sound playback, not realtime input conversion. Rapid-repeat prevention evaluates the actual output interval after timing correction.

## Automatic Sustain Generation

When `Automatic sustain generation` is enabled, the pedal is depressed after an attack and is released or re-pedalled only where the following harmony requires it.

- Semitone conflicts, low-register overlap, retained-note count, hold duration, and total range are checked to prevent muddy playback.
- Short staccato notes and percussion on MIDI channel 10 are not pedalled.
- If source MIDI or realtime input supplies CC64 on a channel, those explicit pedal events take priority.
- The feature applies to MIDI-file key conversion, MIDI sound playback, realtime input conversion, and realtime preview sound.

## Key Bindings

Use `Settings > Key Bindings` to change the output keys for the C3-B5 three-octave range.

- Select a key field and press a key to assign it.
- Duplicate assignments are shown in red.
- `Restore Defaults` restores all bindings to the current default map.
- Sustain, Octave down, and Octave up keys can also be changed.
- Changes are applied immediately to MIDI file keyboard conversion and realtime input conversion.
- Only bindings changed from the default are saved to the settings file.

## Usage

1. Extract the entire release ZIP, then launch `BPSR_MIDI_to_KEY_Player.exe` inside the `BPSR_MIDI_to_KEY_Player` folder.
2. Select `File > Select MIDI Folder` and choose a folder containing MIDI files.
3. Select a MIDI file from the MIDI list.
4. Double-click a MIDI file if you only want to play its MIDI sound.
5. Select `MIDI Input Conversion` and press the shared Start button to play the selected MIDI as keyboard input.
6. Select `Realtime Input Conversion` and press the shared Start button to convert a USB MIDI keyboard in realtime.
7. During countdown, focus the target application that should receive keyboard input.
8. Enable `Play sound` to hear the conversion output while sending key input.

Keyboard output is sent to whichever application is focused at that moment.

## Concurrent Use And Repeat Prevention

MIDI sound playback and realtime input conversion can be used at the same time.
MIDI file keyboard conversion and realtime input conversion cannot be used at the same time.

Repeat prevention applies to MIDI file keyboard conversion, MIDI sound playback, and realtime input conversion. For MIDI files, it evaluates the actual interval after playback speed, timing variation, and chord spread are applied; for realtime input, it evaluates the actual output interval after reception. Repeats to the same converted target below 50 ms are suppressed. Realtime preview sound follows the same rule, and the note-off belonging to a suppressed note is consumed without stopping an accepted note.

## Permissions

Administrator privileges are usually not required.

The app uses the Windows `SendInput` API for keyboard output. If the target application is running as administrator, Windows may block input from this app when it is running as a normal user. In that case, launch this app with the same privilege level as the target application.

To prevent accidental input, keyboard output from this app is suppressed while its main window or a child window has focus.

## Settings File

Settings are saved in the extracted application folder:

```text
BPSR_MIDI_to_KEY_Player\settings.json
```

Settings are saved atomically to reduce the chance of broken settings after an interrupted write.
Normal setting changes are saved together when the application exits. Use `File > Save Settings` to save them immediately.

## Requirements

- Windows
- A folder containing MIDI files when using MIDI file playback
- A USB MIDI input device when using realtime input conversion

## Version

v1.7.1

## Copyright

© 2026 airknightjp
