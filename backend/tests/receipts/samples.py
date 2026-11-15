"""Realistic reconstructed-row receipt texts, as the layout step would produce them."""

WALMART = """\
                 Walmart
         Save money. Live better.
           ( 801 ) 555 - 0142
           MANAGER DANA CLARKE
             1234 S STATE ST
         SALT LAKE CITY UT 84111
  ST# 03456 OP# 009055 TE# 55 TR# 01234
GV WHL MLK     007874235186 F     3.48 N
GV LG WHT EGG  007874237003 F     2.42 N
BANANAS        000000004011 KF
   1.23 lb @ 1 lb /0.58           0.71 N
GV SPRING WTR  007874202906 F
   2 AT 1 FOR 0.98                1.96 N
CHEERIOS       001600027526 F     4.12 N
TIDE PODS      003700087565      12.97 X
           ** VOIDED ENTRY **
CHEERIOS       001600027526 F     4.12-N
MKS CHKN BRST  026137600000 F     9.47 N
                      SUBTOTAL   31.01
            TAX 1  6.850 %        0.89
                         TOTAL   31.90
          VISA TEND              31.90
  ACCOUNT #   **** **** **** 1234 S
  APPROVAL # 012345
  REF # 123456789012
  TERMINAL # SC010203
           CHANGE DUE             0.00
             # ITEMS SOLD 7
     TC# 1234 5678 9012 3456 7890
   Low Prices You Can Trust. Every Day.
        11/03/26        14:22:10
"""

# Same receipt as OCR tends to return it: O/0 and l/1 swaps, a comma for a decimal
# point, a glued department flag, a lower-case unit, keyword misspellings.
WALMART_NOISY = """\
                 WaImart
         Save money. Live better.
GV WHL MLK     0O7874235186F      3,48 N
GV LG WHT EGG  007874237O03 F     2.42 N
BANANAS        000000004011 KF
   1.23 Ib @ 1 lb /0.58           0.71 N
GV SPRING WTR  007874202906 F
   2 AT 1 FOR 0.98                1.96 N
CHEERIOS       0016000275Z6 F     4.12 N
TIDE PODS      003700087565      12.97X
           ** VOIDED ENTRY **
CHEERIOS       001600027526 F     4.12-N
MKS CHKN BRST  026137600000 F     9.47 N
                      SUBT0TAL   31.01
            TAX 1  6.850 %        0.89
                         TOTAI   31.90
          VISA TEND              31.90
             # ITEMS SOLD 7
        11/03/26        14:22:10
"""

# A blurry photo: half the prices are gone or unreadable.
WALMART_BLURRY = """\
                 Walmart
GV WHL MLK     007874235186 F     3.48 N
GV LG WHT EGG  007874237003 F
BANANAS        000000004011 KF
GV SPRING WTR  0078742O2
CHEERIOS       001600027526 F     4.12 N
TIDE PODS      00370008
MKS CHKN BRST  026137600000 F     9.47 N
                      SUBTOTAL   31.01
                         TOTAL   31.90
"""

COSTCO = """\
                  COSTCO
                WHOLESALE
           West Valley #1234
             3655 W 2100 S
       West Valley City, UT 84120
         Member 111222333444
E   1234567 KS ORG EGGS            7.99 N
E    512515 KS WATER 40PK          4.99 N
     0000356151 / 512515           1.00-
E    968123 ORG BANANAS            1.99 N
    1675112 PAPER TOWELS          19.99 A
E   1234567 KS ORG EGGS            7.99 N
     0000361234 / 1675112          4.00-
                  SUBTOTAL        37.95
                       TAX         1.10
               **** TOTAL         39.05
XXXXXXXXXXXX1234 CHIP read
AID: A0000000031010
VISA        Resp: APPROVED
Tran ID#: 123456789
VISA                              39.05
CHANGE                             0.00
A 6.85% TAX                        1.10
TOTAL TAX                          1.10
TOTAL NUMBER OF ITEMS SOLD = 5
INSTANT SAVINGS                   $5.00
11/03/2026 15:04 1234 5 678 900
"""

COSTCO_NOISY = """\
                  C0STCO
                WHOLESALE
E   l234567 KS ORG EGGS            7.99 N
E    512515 KS WATER 40PK          4,99 N
     0000356151 1 512515           1.00-
E    968123 ORG BANANAS            1.99 N
    1675112 PAPER TOWELS          19.99 A
E   1234567 KS ORG EGGS            7.99 N
     0000361234 / 1675112          4.00 -
                  SUBTOTAL        37.95
                       TAX         1.10
               **** TOTAL         39.05
TOTAL NUMBER OF ITEMS SOLD = 5
11/03/2026 15:04
"""

SMITHS = """\
                 Smith's
           Smith's Food & Drug
              455 S 500 E
        Salt Lake City, UT 84102
        Store Manager: Jim Doe
            (801) 555-0199
KRO 2% MILK GAL               3.29 B
   SC KROGER SAVINGS          0.50-
2 @ 2/5.00
PRIVATE SEL CHIPS             5.00 B
2.31 lb @ 1.99 /lb
WT      BANANAS               4.60 B
SIMPLE TRUTH ORG SPINACH      3.99 B
   MFR COUPON                 1.00-
TIDE DETERGENT               11.99 T
   SC KROGER SAVINGS          2.00
                    TAX       0.81
         **** BALANCE        26.18
VISA                         26.18
CHANGE                        0.00
TOTAL NUMBER OF ITEMS SOLD = 6
     TOTAL SAVINGS             3.50
11/03/26 2:22pm 455 12 345 6789
SMITH'S REWARDS CUSTOMER ****1234
FUEL POINTS EARNED TODAY: 26
Fuel Points This Month: 312
"""

# Fred Meyer with OCR noise and a voided item: the cashier rang up the chips twice.
FRED_MEYER_NOISY = """\
              FRED MEYER
KRO 2% MILK GAL               3.Z9 B
   SC KROGER SAVINGS          O.50
PRIVATE SEL CHIPS             2.50 B
PRIVATE SEL CHIPS             2.50 B
PRIVATE SEL CHIPS             2.50-B
2.31 Ib @ 1.99 /lb
WT      BANANAS               4.60 B
                    TAX       0.31
         **** BALANCE        10.20
TOTAL NUMBER OF ITEMS SOLD = 3
11/04/26 9:05am
"""

TRADER_JOES = """\
TRADER JOE'S
2281 E Fort Union Blvd
Cottonwood Heights UT 84121
OPEN 8:00AM TO 9:00PM DAILY
SALES TRANSACTION
ORGANIC BANANAS              1.14
  3 @ 0.38
MANDARIN ORANGE CHICKEN      4.99
UNEXPECTED CHEDDAR           4.49
SPARKLING WATER              3.98
  2 @ 1.99
Items in Transaction: 7
SUBTOTAL                   $14.60
TOTAL                      $14.60
VISA                       $14.60
CHANGE                      $0.00
11-03-2026 06:40PM
THANK YOU FOR SHOPPING AT TRADER JOE'S
"""
