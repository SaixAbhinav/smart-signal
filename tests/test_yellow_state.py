from smartsignal.env.traffic_signal import make_yellow_state


def test_greens_losing_right_of_way_turn_yellow():
    old = "GGGgrrrr"
    new = "rrrrGGGg"
    assert make_yellow_state(old, new) == "yyyyrrrr"


def test_greens_kept_stay_green():
    old = "GGrr"
    new = "Grrr"  # first signal stays green
    assert make_yellow_state(old, new) == "Gyrr"


def test_reds_becoming_green_stay_red_during_yellow():
    old = "rrGG"
    new = "GGrr"
    assert make_yellow_state(old, new) == "rryy"
