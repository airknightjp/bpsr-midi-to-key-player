# BPSR MIDI to KEY Player

[日本語](README.md) | [中文](README.zh-CN.md)

BPSR MIDI to KEY Player is a Windows desktop tool that converts MIDI files and USB MIDI keyboard input into keyboard events.

It is designed for BPSR-style keyboard performance: MIDI notes are mapped to ordinary keyboard keys, and the converted input is sent to the currently focused application. The app also includes MIDI sound playback, channel filtering, realtime MIDI input conversion, range fitting, global shortcuts, themes, and tray-resident operation.

## Features

- Load a folder containing `.mid` and `.midi` files.
- Display loaded MIDI files in a list with their duration.
- Double-click a MIDI file in the list to play or stop MIDI sound playback.
- Convert MIDI files into BPSR-style keyboard input.
- Convert realtime USB MIDI keyboard input into keyboard input.
- When test mode is enabled, starting realtime input monitoring plays received notes at the configured MIDI volume.
- Play MIDI sound without creating temporary MIDI playback files.
- Control playback position with a seek slider.
- Change MIDI playback volume with a volume slider.
- Adjust playback speed from 50% to 200% and apply changes immediately during playback. Double-click the playback speed label to reset it to 100%.
- Humanize playback with subtle timing variation and toggle it immediately during playback.
- Apply chord strum to chords of two or more notes with a short, randomized note order and timing spread.
- Prevent rapid repeats by ignoring repeated notes less than 50 ms apart during MIDI file conversion and MIDI sound playback.
- Select only the channels used by the loaded MIDI file.
- Apply channel on/off changes during playback.
- Convert sustain pedal CC64 to the Space key.
- Optionally fit notes into the C3-B5 three-octave range.
- Adjust transpose (-12 to +12 semitones) and octave shift (-3 to +3) from Common Settings, with immediate updates during playback and realtime input. Double-click either setting label to reset it to 0.
- Handle notes outside C3-B5 by using octave shift keys when range fitting is disabled.
- Start MIDI input conversion after an optional countdown.
- Optionally play a sound during countdown.
- Use test mode to write conversion logs without sending real keyboard input.
- Configure global start and stop shortcuts by pressing the desired keys.
- Lock shortcut settings to avoid accidental changes.
- Save settings such as volume, playback speed, transpose, octave shift, timing variation, chord strum, repeat prevention, countdown, test mode, theme, shortcuts, window height, and the last loaded MIDI folder.
- Automatically reload the previous MIDI folder on the next launch.
- Switch UI language between English, Japanese, and Chinese.
- Choose from multiple color themes.
- Adjust window opacity and double-click the opacity label to reset it to 100%.
- Keep the window always on top.
- Minimize to the task tray and restore from the tray icon.
- Prevent duplicate instances and bring the existing window to the front when launched again.

## Note Range

The base BPSR keyboard range is C3-B5.

- C3-B5 is played directly.
- Lower notes can be played by switching to the low octave range.
- Higher notes can be played by switching to the high octave range.
- When `Fit to 3 octaves` is enabled, notes outside C3-B5 are moved by octaves until they fit inside the C3-B5 range.

This range fitting is applied to both MIDI file keyboard conversion and realtime USB MIDI input conversion.

Transpose and octave shift apply to MIDI file keyboard conversion, realtime input conversion, MIDI sound playback, and realtime preview sound. Range fitting or normal out-of-range handling is applied after the pitch shift.

## Usage

1. Launch `BPSR_MIDI_to_KEY_Player.exe`.
2. Click `Load MIDI Folder` and select a folder containing MIDI files.
3. Select a MIDI file from the MIDI list.
4. Double-click the MIDI file if you want to play its MIDI sound.
5. Use `MIDI Input Conversion` if you want to play the selected MIDI as keyboard input.
6. Use `Realtime Input Conversion` if you want to convert a USB MIDI keyboard into keyboard input.
7. During countdown, focus the target application that should receive the keyboard input.
8. Enable `Test mode (log only)` when you want to confirm the conversion log without sending real keys.

Keyboard output is sent to whichever application is currently focused.

## Permissions

Administrator privileges are usually not required.

The app uses the Windows `SendInput` API for keyboard output. It can send input to normal desktop applications when running as a normal user. If the target application is running as administrator, Windows may block input from a non-administrator process. In that case, launch this app with the same privilege level as the target application.

## Settings

Settings are saved under the current Windows user profile:

```text
%APPDATA%\BPSR_MIDI_to_KEY_Player\settings.json
```

Settings are saved atomically to reduce the chance of broken settings after an interrupted write.

## Requirements

- Windows
- A MIDI file folder for file playback
- A USB MIDI input device, only when using realtime input conversion
