"""
Chess at Rau's table.

The second game on the table, and the one where the two halves of him come
apart most clearly. Kittens is played by a model: `kittens/player.py` reads the
hand, picks a legal move, and lives with it. Here the model plays nothing.
Stockfish picks every move, at a strength that quietly tracks how you have been
doing, and Rau's half of this package is entirely performance — the pause before
he commits, the claw that goes out toward a piece and comes back, the line said
across the table while the clock is not running.

That is not a shortcut. A model that plays chess badly and a model that pretends
to play chess are different products, and only one of them is worth sitting down
opposite. So the layers are:

    binary · engine · level · timing     what to play, how strong, how long to wait
    board                                the position, the rules, what survives a restart
    player · banter · pump · session     the man across the table

Nothing in the second group is allowed to choose a move, and nothing in the
first group is allowed to speak.
"""
