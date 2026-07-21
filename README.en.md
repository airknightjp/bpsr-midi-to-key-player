# BPSR MIDI to KEY Player

[日本語](README.md) | [中文](README.zh-CN.md)

> **Multilingual UI:** Supports Japanese, English, and Chinese.

BPSR MIDI to KEY Player is a Windows desktop tool that converts MIDI files and USB MIDI keyboard input into keyboard events.

It is designed for BPSR-style keyboard performance. MIDI notes are mapped to ordinary keyboard keys and sent to the currently focused application. The app also supports MIDI sound playback, track/channel selection, realtime input conversion, note range adjustment, custom key bindings, global shortcuts, themes, and task tray storage.

## Features

- Load folders containing `.mid` and `.midi` files.
- Show name, duration, and note range in the MIDI list.
- Double-click a MIDI file to play or stop MIDI sound playback.
- Convert MIDI files into keyboard input.
- Convert realtime USB MIDI keyboard input into keyboard input.
- Use test mode to log conversion output without sending real key input.
- Adjust volume, playback position, and playback speed (10-200%). Double-click the volume or speed label to reset it to 100%.
- Adjust UI scale (100-200%) and window opacity from the View menu.
- Adjust transpose (-12 to +12 semitones) and octave shift (-3 to +3) above the player. Double-click either label to reset to 0.
- Optionally fit notes into the C3-B5 three-octave range.
- Handle notes outside C3-B5 with octave-switch keys when range fitting is disabled.
- Configure timing variation, chord spread, and chord reconstruction under Performance Correction.
- Configure rapid-repeat prevention under Common Settings.
- Display used track/channel combinations under a `TC` header in `11` format.
- Toggle each track/channel combination, with immediate changes during playback.
- Convert sustain pedal CC64 to the Space key.
- Configure a countdown before MIDI input conversion starts.
- Play countdown sound and optionally press the in-game C3 key for ensemble use.
- Log countdown ticks and in-game countdown key presses.
- Configure global start, pause, and stop shortcuts by pressing keys. The defaults are F9, F10, and F11, and standalone function keys are supported.
- Lock shortcut settings to avoid accidental changes.
- Edit the three-octave C3-B5 key bindings from `Settings > Key Bindings`.
- Highlight duplicate key bindings in red.
- Restore all key bindings to their defaults.
- Switch UI language between Japanese, English, and Chinese.
- Choose from multiple color themes, including Sky Blue. Sky Blue is the default for new settings.
- Save always-on-top, window size including enlarged layouts, and the last loaded MIDI folder.
- Show or hide each of the four main sections from the View menu.
- Support `[Close] to tray`.
- Prevent duplicate instances.
- Show version, copyright, and GitHub link from `Other > About BPSR MIDI to KEY Player`.

## Menus

- `File > Select MIDI Folder`: Select a folder containing MIDI files.
- `File > Exit`: Fully exit the app.
- `View`: Change scale, opacity, always-on-top, and section visibility.
- `Settings`: Change theme, language, key bindings, and tray behavior.
- `Other > About BPSR MIDI to KEY Player`: Show version information and the GitHub link.

## Note Range

The base BPSR keyboard range is C3-B5.

- Notes in C3-B5 are played directly.
- Lower notes can be played by switching to the low octave range.
- Higher notes can be played by switching to the high octave range.
- When `Fit to 3 octaves` is enabled, notes outside C3-B5 are moved by octaves until they fit inside C3-B5.

Transpose and octave shift apply to MIDI file keyboard conversion, realtime input conversion, MIDI sound playback, and realtime preview sound. Range fitting or normal out-of-range handling is applied after the pitch shift.

## Chord Reconstruction

When `Chord reconstruction` is enabled, notes starting within approximately 35 ms are analyzed as one chord and rearranged by octaves into a playable form.

- The top voice, bass, common tones, voice order, and smooth movement between adjacent chords are prioritized while excessive spacing, physical-key collisions, and frequent range switches are discouraged.
- A sufficiently long rest is treated as a phrase boundary. After the boundary, the planner can select a range suited to the new phrase without being overly constrained by the preceding voicing.
- With `Fit to 3 octaves` enabled, every optimized chord stays inside C3-B5.
- With range fitting disabled, the low, normal, and high ranges are compared, and `<` or `>` is used only where the optimized chord benefits from a range change.
- With range fitting disabled, the current playback speed is evaluated continuously. Slower playback can use the added real-time switching margin to select a wider range, while faster playback avoids unnatural consecutive range changes. Changes made during playback take effect immediately.
- During initial planning, the status shows progress from `Optimizing 0%` through `Optimizing 100%`. The playback clock starts after the plan is ready.
- Replanning during playback runs in the background and playback continues with the current plan until the replacement is ready. Continuous speed changes are debounced for 150 ms and obsolete calculations are cancelled.
- If every note cannot be placed at once, redundant notes or inner voices are omitted before the top voice or bass.
- This applies to MIDI file keyboard conversion and MIDI sound playback, not realtime input conversion.

When `Chord spread` is also enabled, exactly simultaneous chords lead with the top voice and delay inner voices slightly more than outer voices. Stronger notes are also biased toward earlier onsets, with a maximum difference of 12 ms. Existing onset differences in the MIDI are preserved. These planned offsets are not applied while `Chord spread` is disabled.

`Timing variation` remains a separate small timing variation applied to the chord as a group. Rapid-repeat prevention evaluates the converted physical key after chord reconstruction.

## Key Bindings

Use `Settings > Key Bindings` to change the output keys for the C3-B5 three-octave range.

- Select a key field and press a key to assign it.
- Duplicate assignments are shown in red.
- `Restore Defaults` restores all bindings to the current default map.
- Changes are applied immediately to MIDI file keyboard conversion and realtime input conversion.
- Only bindings changed from the default are saved to the settings file.

## Usage

1. Launch `BPSR_MIDI_to_KEY_Player.exe`.
2. Select `File > Select MIDI Folder` and choose a folder containing MIDI files.
3. Select a MIDI file from the MIDI list.
4. Double-click a MIDI file if you only want to play its MIDI sound.
5. Use `MIDI Input Conversion > Start Playback` to play the selected MIDI as keyboard input.
6. Use `Realtime Input Conversion > Start Listening` to convert a USB MIDI keyboard in realtime.
7. During countdown, focus the target application that should receive keyboard input.
8. Enable `Test mode (log only)` when you want to check the conversion log without sending real keys.

Keyboard output is sent to whichever application is focused at that moment.

## Concurrent Use And Repeat Prevention

MIDI sound playback and realtime input conversion can be used at the same time.
MIDI file keyboard conversion and realtime input conversion cannot be used at the same time.

Repeat prevention applies to MIDI file keyboard conversion, MIDI sound playback, and realtime input conversion. For MIDI files, it evaluates the actual interval after playback speed, timing variation, and chord spread are applied; for realtime input, it evaluates the actual output interval after reception. Repeats to the same converted target below 50 ms are suppressed. Realtime preview sound follows the same rule, and the note-off belonging to a suppressed note is consumed without stopping an accepted note.

## Permissions

Administrator privileges are usually not required.

The app uses the Windows `SendInput` API for keyboard output. If the target application is running as administrator, Windows may block input from this app when it is running as a normal user. In that case, launch this app with the same privilege level as the target application.

## Settings File

Settings are saved under the current Windows user profile:

```text
%APPDATA%\BPSR_MIDI_to_KEY_Player\settings.json
```

Settings are saved atomically to reduce the chance of broken settings after an interrupted write.

## Requirements

- Windows
- A folder containing MIDI files when using MIDI file playback
- A USB MIDI input device when using realtime input conversion

## Version

v1.2.0

## Copyright

© 2026 airknightjp
