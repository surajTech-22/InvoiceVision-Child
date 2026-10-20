def normalize(s):
    return " ".join(str(s).casefold().split())

def is_conflict(a, b):
    return normalize(a) != normalize(b)

def numeric_conflict(a, b):
    a = "".join(c for c in str(a) if c.isdigit())
    b = "".join(c for c in str(b) if c.isdigit())
    return a != b

def test():
    assert numeric_conflict("152.04", "162.04")
    assert not numeric_conflict("1,430.00", "1430.00")
    assert is_conflict("Tax amount", "Tax armt")
    print("Research-only disagreement checks passed")

if __name__ == "__main__":
    test()
