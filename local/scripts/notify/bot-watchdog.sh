#!/bin/bash
SERVICE=agent-bot-blue.service
if ! /usr/bin/sudo -n /usr/bin/systemctl is-active --quiet "$SERVICE"; then
    /usr/bin/sudo -n /usr/bin/systemctl reset-failed "$SERVICE" 2>/dev/null
    /usr/bin/sudo -n /usr/bin/systemctl start "$SERVICE"
fi
