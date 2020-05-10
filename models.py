import datetime
import requests
import pytz
import pandas
import sqlalchemy as db
from sqlalchemy_utils import TimezoneType
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import Insert
from config import Config
import scraper


# Replace all 'INSERT' queries with 'INSERT OR IGNORE' to avoid IntegrityError's on duplicate entries
# This is a global change so could have further implications
# https://stackoverflow.com/questions/2218304/sqlalchemy-insert-ignore
@compiles(Insert)
def _prefix_insert_with_ignore(insert, compiler, **kw):
    return compiler.visit_insert(insert.prefix_with('OR IGNORE'), **kw)

engine = db.create_engine('sqlite:///test.db', echo=True)
Base = declarative_base(bind=engine)


class Tools:
    time_format = '%H:%M %d/%m/%y'
    aus_tz = pytz.timezone('Australia/Sydney')
    time = datetime.datetime.now(aus_tz).strftime(time_format)
    market_open = datetime.time(10, 0, 0, tzinfo=aus_tz)
    market_close = datetime.time(16, 0, 0, tzinfo=aus_tz)


class Market(Base):
    __tablename__ = 'market'
    code = db.Column(db.String, primary_key=True)
    name = db.Column(db.String)
    api_code = db.Column(db.String)
    timezone = db.Column(TimezoneType(backend='pytz'))
    open = db.Column(db.Time(timezone=True))
    close = db.Column(db.Time(timezone=True))
    base_url = db.Column(db.String)

    # Foreign key relationships
    stocks = relationship('Stock', order_by='Stock.ticker', back_populates='market')

    def __init__(self, code, **kwargs):
        self.code = code
        self.name = kwargs.pop('name', None)
        self.api_code = kwargs.pop('api_code', None)
        self.timezone = kwargs.pop('timezone', None)
        self.open = kwargs.pop('open', None)
        self.close = kwargs.pop('close', None)
        self.base_url = kwargs.pop('base_url', None)

    def get_all_stocks(self):
        pass


class Stock(Base):
    __tablename__ = 'stock'
    ticker = db.Column(db.String, primary_key=True)
    name = db.Column(db.String)
    url = db.Column(db.String)
    price = db.Column(db.Float)
    price_time = db.Column(db.DateTime)
    shares_issued = db.Column(db.Integer)
    sector = db.Column(db.String)
    last_updated = db.Column(db.DateTime)
    type = db.Column(db.String)

    # Link stock data to markets table via market code
    market_code = db.Column(db.String, db.ForeignKey('market.code'))
    market = relationship('Market', back_populates='stocks')

    # Relate stock to any LICs that hold it TODO not sure if I need this line as I don't care about this association
    #holder_ticker = db.Column(db.String, db.ForeignKey('lic.ticker'))
    #holders = relationship('LIC', foreign_keys=[holder_ticker], secondary='holding')

    # Map polymorphism identifier for Single Table Inheritance with LIC table
    # https://docs.sqlalchemy.org/en/13/orm/inheritance.html
    __mapper_args__ = {'polymorphic_identity': 'stock',
                       'polymorphic_on': type}

    def __init__(self, ticker, market_code, **kwargs):
        self.ticker = ticker
        self.market_code = market_code
        self.name = kwargs.pop('name', None)
        self.url = kwargs.pop('url', None)
        self.price = kwargs.pop('price', None)
        self.price_time = kwargs.pop('price_time', None)
        self.shares_issued = kwargs.pop('shares_issued', None)
        self.sector = kwargs.pop('sector', None)
        self.last_updated = datetime.datetime(2000, 1, 1, 00, 00)  # Default time to allow initial condition testing

        # Get initial data
        self.get_stats()
        self.update_price()

    def get_price_data(self):
        # Get 5min intraday data for this ticker on the ASX TODO could use the Quote Endpoint (GLOBAL_QUOTE) here instead but it doesnt give a price data timestamp
        params = {'function': 'TIME_SERIES_INTRADAY',
                  'symbol': self.ticker + '.' + 'AX', #self.market.api_code, TODO stock-market association isnt made until after objs are committed to db, so this attr does not exist when calling this method from init
                  'interval': '5min',
                  'apikey': Config.api_key}
        response = requests.get('https://www.alphavantage.co/query', params=params)

        # Store time of data retrieval
        self.last_updated = datetime.datetime.strptime(response.headers['Date'], '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=pytz.timezone('Etc/GMT'))
        return response.json()

    def update_price(self):
        # Last data API call was over 5 mins ago, then fetch fresh data
        if (datetime.datetime.now() - self.last_updated) / 60 > datetime.timedelta(seconds=300):
            data = self.get_price_data()

            # Get time information from data
            us_timezone = data['Meta Data']['6. Time Zone']
            us_time_str = list(data['Time Series (5min)'].keys())[0]
            us_time = datetime.datetime.strptime(us_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.timezone(us_timezone))

            # Get price and local time
            self.price_time = us_time.astimezone(Tools.aus_tz)
            self.price = float(data['Time Series (5min)'][us_time_str]['4. close'])

    def get_stats(self):
        # Create scraper objects for different pages to scrape
        stats_fetcher = scraper.StatisticsFetcher()
        details_fetcher = scraper.DetailsFetcher()

        # Scrape!
        stats = stats_fetcher.fetch(self.ticker)
        details = details_fetcher.fetch(self.ticker)

        self.shares_issued = int(stats['shares issued'])
        self.url = details['url']
        self.sector = details['sector']
        self.name = details['name']


class LIC(Stock):
    cash = db.Column(db.Integer)
    NTA = db.Column(db.Float)
    NTA_time = db.Column(db.DateTime)

    holding_ticker = db.Column(db.String, db.ForeignKey('stock.ticker'))  # had ForeignKey('holding.holding_ticker') here and produces different error
    holdings = relationship('Stock', foreign_keys=[holding_ticker], secondary='holding')

    # Map polymorphism identifier for Single Table Inheritance with stock table
    __mapper_args__ = {'polymorphic_identity': 'LIC'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cash = kwargs.pop('cash', None)
        self.holdings = kwargs.pop('holdings', [])
        self.NTA = kwargs.pop('NTA', None)
        self.NTA_time = kwargs.pop('NTA_time', None)
        #self.update_NTA()

    def update_NTA(self):
        total_assets = self.cash
        for holding in self.holdings:
            total_assets += holding['ticker'].price * holding['units']
        self.NTA = total_assets / self.shares_issued
        self.NTA_time = Tools.time

    def modify_holding(self, stock, units):
        # TODO see if object for ticker already exists in DB, if not create it
        # if ticker in holdings table then update units else add ticker and units to holdings table
        if stock in self.holdings.holding_ticker:
            self.holdings.holding_ticker['units'] = units
        else:
            self.holdings.loc[stock.ticker] = {'holding': stock, 'units': units}


class Holding(Base):
    # Many to many relationship between LIC and Stock tables
    __tablename__ = 'holding'
    LIC_ticker = db.Column(db.String, db.ForeignKey('stock.ticker'), primary_key=True)
    holding_ticker = db.Column(db.String, db.ForeignKey('stock.ticker'), primary_key=True)
    units = db.Column(db.Integer)


if __name__ == '__main__':
    Base.metadata.create_all()

    Session = sessionmaker(bind=engine)
    s = Session()
    asx = Market('ASX', api_code='AX')
    cnu = Stock('CNU', 'ASX')
    arg = LIC('ARG', 'ASX')
    arg.holdings.append(cnu)
    s.add_all([asx, cnu, arg])
    s.commit()
