"""R138 isolated CPU geometry tests, research-only."""
import math

def weighted_word_score(text, confidence):
    count=sum(ch.isalnum() for ch in text)
    if count<1 or confidence<0:return 0.0
    return min(12,count)**.75*(min(confidence,100)/100)**2*(.25 if count==1 else 1.0)

def test():
    assert weighted_word_score("INVOICE",90)>weighted_word_score("I",90)
    assert weighted_word_score("1234",90)>weighted_word_score("1234",50)
    assert weighted_word_score("",99)==0.0
    print("CPU orientation scoring invariant passed")

if __name__=="__main__":test()
