#!/bin/bash
# Documented building blocks any port may use (not a template of its own): pmcheck treats these lines as known.

# Bulk data shipped as a .tar.gz, extracted on first launch
ARCHIVE_FILE="gamedata.tar.gz"
if [[ -f "$ARCHIVE_FILE" ]]; then
    pm_message "Extracting game data, this can take a few minutes..." --title "Please wait"
    if ! gunzip -c "$ARCHIVE_FILE" | tar --no-same-owner -xf -; then
        pm_show_error "Could not extract $ARCHIVE_FILE." --title "Extraction failed"
        exit 1
    fi
    $ESUDO rm -f "$ARCHIVE_FILE"
elif [ ! -f 'gamedata/known-file' ]; then
    pm_show_error "No game data found." --title "Game data missing"
    exit 1
fi
ARCHIVE_FILES=(gamedata.tar.gz.part*)
if [[ -f "${ARCHIVE_FILES[0]}" ]]; then
    [[ -d 'gamedata/' ]] && $ESUDO rm -fR 'gamedata/'
    if ! cat "${ARCHIVE_FILES[@]}" | gunzip -c | tar --no-same-owner -xf -; then
        exit 1
    fi
    $ESUDO rm -f "${ARCHIVE_FILES[@]}"
fi

# Default config copied on first launch, bound files
[ -f "$GAMEDIR/conf/game.cfg" ] || cp "$GAMEDIR/game_default.cfg" "$GAMEDIR/conf/game.cfg"
touch "$GAMEDIR/conf/.gamerc"
bind_files ~/.gamerc "$GAMEDIR/conf/.gamerc"

# Mouse-driven ports: faster cursor on high-resolution screens, D-pad mouse without sticks
if [ "${DISPLAY_WIDTH:-640}" -gt 1280 ]; then
  sed -i "s/^deadzone_scale = .*/deadzone_scale = 18/" "$GAMEDIR/game.ini"
fi
if [ "$ANALOG_STICKS" = "0" ]; then
  sed -i "s/^r2 = .*/r2 = hold_state dpad_mouse/" "$GAMEDIR/game.ini"
fi

# ROCKNIX: sway owns the touchscreen and the cursor
if [ "$CFW_NAME" = "ROCKNIX" ]; then
  export SDL_TOUCH_MOUSE_EVENTS=0
  swaymsg input type:touch events disabled 2>/dev/null
  swaymsg seat '*' hide_cursor 0 2>/dev/null
  trap 'swaymsg seat "*" hide_cursor 1000 2>/dev/null' EXIT
fi

# OmniOSK on-screen keyboard (L2), preloaded into the game only
export OMNI_EVENT_MODE=key
LD_PRELOAD="$GAMEDIR/libs.${DEVICE_ARCH}/libomni_osk.so${LD_PRELOAD:+:$LD_PRELOAD}" ./$BINARY

# 32-bit games: before mod_<CFW>.txt
export PORT_32BIT="Y"
$ESUDO chmod +x "$GAMEDIR/$BINARY"
