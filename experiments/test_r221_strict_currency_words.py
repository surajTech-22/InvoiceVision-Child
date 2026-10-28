import unittest
from decimal import Decimal
from r221_strict_currency_words import parse_amount_words

class IndianCurrencyWordsTests(unittest.TestCase):
    def test_valid_source_phrases(self):
        cases = {
          'RUPEES SIX THOUSAND NINE HUNDRED SIXTY SIX': '6966.00',
          'RUPEES SIX THOUSAND NINE HUNDRED SIXTY SIX ONLY': '6966.00',
          'RUPEES ONE HUNDRED AND FIVE ONLY': '105.00',
          'RUPEES ONE LAKH TWENTY THOUSAND FOUR HUNDRED ONLY': '120400.00',
          'RUPEES FIFTY ONE THOUSAND ONLY': '51000.00',
          'RUPEES SIX THOUSAND NINE HUNDRED SIXTY SIX AND FIFTY PAISE ONLY': '6966.50',
          'RUPEES ZERO AND FIVE PAISE ONLY': '0.05',
          'RUPEES ONE CRORE TWO LAKH THREE THOUSAND FOUR HUNDRED FIVE ONLY': '10203405.00',
        }
        for words, expected in cases.items():
            with self.subTest(words=words):
                self.assertEqual(parse_amount_words(words), Decimal(expected))

    def test_malformed_ocr_and_grammars_fail_closed(self):
        cases = [
          'RUPEES SIX SIX ONLY', 'RUPEES TWENTY THIRTY ONLY',
          'RUPEES ONE ONE ONLY', 'RUPEES TWENTY THOUSAND THOUSAND ONLY',
          'RUPEES SIX THOUSAND NINE HUNDRED SIXTY SlX ONLY',
          'RUPEES SIX THOUSAND PAISA', 'RUPEES SIX THOUSAND FIFTY PAISE',
          'RUPEES SIX THOUSAND AND ONE HUNDRED PAISE ONLY',
          'RUPEES SIX HUNDRED AND ONLY', 'RUPEES ONE HUNDRED HUNDRED',
          'RUPEES ONE HUNDRED FIFTY ONE HUNDRED ONLY',
          'RUPEES FIFTY ONE LAKH TWO CRORE ONLY',
          'RUPEES ZERO THOUSAND ONLY', 'RUPEES THOUSAND ONLY',
          'RUPEES ONE THOUSAND AND TWO HUNDRED PAISE',
          'RUPEES 100 ONLY', 'RUPEES TWO ONLY ONLY',
          'RUPEES TWO PAISE ONLY', 'RUPEES TWO AND ZERO PAISE',
          'RUPEES ONE HUNDRED AND AND THREE PAISE',
          '', None, 33,
        ]
        for words in cases:
            with self.subTest(words=words):
                self.assertIsNone(parse_amount_words(words))

if __name__=='__main__': unittest.main(verbosity=2)
