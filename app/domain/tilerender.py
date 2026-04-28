def tile_to_3x3(tile: TileNode) -> list[list[str]]:
    if tile.tile_type == "room":
        layout = [
            ["╔", "═", "╗"],
            ["║", " ", "║"],
            ["╚", "═", "╝"]
        ]

        # Open doors replace walls with spaces
        if tile.doors.get("N", False):
            layout[0][1] = " "
        if tile.doors.get("S", False):
            layout[2][1] = " "
        if tile.doors.get("W", False):
            layout[1][0] = " "
        if tile.doors.get("E", False):
            layout[1][2] = " "

        return layout

    elif tile.tile_type in ("corridor", "entrance"):
        layout = [
            [" ", " ", " "],
            [" ", " ", " "],
            [" ", " ", " "]
        ]

        # Draw corridor walls based on open doors
        if tile.doors.get("N", False):
            layout[0][1] = "║"
        if tile.doors.get("S", False):
            layout[2][1] = "║"
        if tile.doors.get("W", False):
            layout[1][0] = "═"
        if tile.doors.get("E", False):
            layout[1][2] = "═"

        # Center tile
        if tile.feature == "fountain":
            layout[1][1] = "F"
        elif tile.feature == "teleport":
            layout[1][1] = "T"
        else:
            # Decide junction character based on doors
            open_doors = [d for d, is_open in tile.doors.items() if is_open]
            open_set = set(open_doors)

            if open_set == {"N", "S"}:
                layout[1][1] = "║"
            elif open_set == {"E", "W"}:
                layout[1][1] = "═"
            elif open_set == {"N", "E"}:
                layout[1][1] = "╚"
            elif open_set == {"N", "W"}:
                layout[1][1] = "╝"
            elif open_set == {"S", "E"}:
                layout[1][1] = "╔"
            elif open_set == {"S", "W"}:
                layout[1][1] = "╗"
            elif open_set == {"N", "S", "E"}:
                layout[1][1] = "╠"
            elif open_set == {"N", "S", "W"}:
                layout[1][1] = "╣"
            elif open_set == {"E", "S", "W"}:
                layout[1][1] = "╦"
            elif open_set == {"E", "N", "W"}:
                layout[1][1] = "╩"
            elif len(open_set) == 4:
                layout[1][1] = "╬"
            else:
                layout[1][1] = "·"  # Default simple corridor if weird shape

        return layout

    else:
        raise ValueError(f"Unknown tile_type: {tile.tile_type}")

def render_full_map(graph: DungeonGraph) -> list[str]:
    # Find bounds
    if not graph.tiles:
        return []

    xs = [x for (x, y) in graph.tiles.keys()]
    ys = [y for (x, y) in graph.tiles.keys()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    width = (max_x - min_x + 1) * 3
    height = (max_y - min_y + 1) * 3

    canvas = [[" " for _ in range(width)] for _ in range(height)]

    for (x, y), tile in graph.tiles.items():
        tile_grid = tile_to_3x3(tile)
        offset_x = (x - min_x) * 3
        offset_y = (max_y - y) * 3  # Notice: y is reversed for top-down drawing

        for dy in range(3):
            for dx in range(3):
                canvas[offset_y + dy][offset_x + dx] = tile_grid[dy][dx]

    # Turn 2D list into list of strings
    return ["".join(row) for row in canvas]


