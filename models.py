import datetime
import requests
import pytz
import pandas
from config import Config
import scraper


class Tools:
    time_format = '%H:%M %d/%m/%y'
    aus_tz = pytz.timezone('Australia/Sydney')
    time = datetime.datetime.now(aus_tz).strftime(time_format)
    market_open = datetime.time(10, 0, 0, tzinfo=aus_tz)
    market_close = datetime.time(16, 0, 0, tzinfo=aus_tz)


class Stock:
    def __init__(self, ticker, name, **kwargs):
        self.ticker = ticker
        self.name = name
        self.url = str()
        self.price = {'price': None, 'time': None}
        self.shares_issued = int()
        self.sector = str()
        self.latest_data = None
        self.latest_update = None

    def get_price_data(self):
        # Get 5min intraday data for this ticker on the ASX TODO could use the Quote Endpoint (GLOBAL_QUOTE) here instead
        params = {'function': 'TIME_SERIES_INTRADAY',
                  'symbol': self.ticker + '.AX',
                  'interval': '5min',
                  'apikey': Config.api_key}
        response = requests.get('https://www.alphavantage.co/query', params=params)

        # Store data and time of retrieval
        self.latest_data = response.json()
        self.latest_update = datetime.datetime.strptime(response.headers['Date'], '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=pytz.timezone('Etc/GMT'))

    def update_price(self):
        # Last data API call was over 5 mins ago, then fetch fresh data
        if (self.latest_update - datetime.datetime.now()) / 60 > 300:
            self.get_price_data()

        # Get time information from data
        us_timezone = self.latest_data['Meta Data']['6. Time Zone']
        us_time = list(self.latest_data['Time Series (5min)'].keys())[0]
        us_time = datetime.datetime.strptime(us_time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.timezone(us_timezone))

        # Get price and local time
        self.price['time'] = us_time.astimezone(Tools.aus_tz).strftime(Tools.time_format)
        self.price['price'] = float(self.latest_data['Time Series (5min)'][us_time]['4. close'])

    def get_shares_issued(self):
        pass

class LIC(Stock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cash = int()
        self.holdings = pandas.DataFrame(columns=['holding', 'units'])
        self.NTA = {'NTA': float(), 'time': str()}

    def update_NTA(self):
        total_assets = self.cash
        for holding in self.holdings:
            total_assets += holding['ticker'].price['price'] * holding['units']
        self.NTA['NTA'] = total_assets / self.shares_issued
        self.NTA['time'] = Tools.time

    def modify_holding(self, stock, units):
        # TODO see if object for ticker already exists in DB, if not create it
        # if ticker in df then update units else add ticker and units to df
        if stock in self.holdings.holding.values:
            self.holdings.loc[stock, 'units'] = units
        else:
            self.holdings.loc[stock.ticker] = {'holding': stock, 'units': units}
