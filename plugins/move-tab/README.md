# herdr-move-tab

A Herdr plugin: press `§ m` on any tab, pick a workspace from a popup (or press `n` and type a name for a new one), and the tab moves there under its own label. Chats running in it keep running.

## How it works

Herdr has no "move tab to workspace" call (`tab.move` only reorders inside a workspace), so the plugin moves the tab's panes with `herdr pane move`:

- The first pane goes into a new tab in the target, under the tab's label.
- The rest of the tab's split tree is rebuilt there from `herdr pane layout`: the same directions and ratios. If the layout can't be read as a tree, the other panes are stacked top to bottom and the notification says so.
- Herdr closes the source workspace once its last tab leaves.

After the move it:

- runs `hive sync` for the queen of any moved hive bee, so hive's record of the bee's tab id stays right and `hive close` still closes the tab;
- tells the target workspace's overseer chat (a chat whose name contains "overseer") about the new tab, but only when that chat is idle.

## Use

- Popup: `§ m`. Keys: up/down or j/k, 1-9, enter to move, `n` for a new workspace, q or esc to cancel.
- CLI, for scripts and agents, run from this folder inside a Herdr pane:
  - `python3 -m herdr_move_tab.cli move <tab_id> --to <workspace_id>`
  - `python3 -m herdr_move_tab.cli move <tab_id> --new "<name>"`

## Install

```sh
herdr plugin link ~/code/tools/hive/plugins/move-tab
```

Then add to `~/.config/herdr/config.toml` and run `herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "move-tab.pick"
description = "Move tab to workspace..."
```

## Tests

```sh
python3 -m unittest discover -s tests
```
