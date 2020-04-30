from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
import pandas


class Scraper:
    def __init__(self):
        """
        Initialise a Scraper instance using chromedriver. This scraper uses UserAgent to generate random, but valid,
        user agents for each instance.
        """
        # Set up random fake user agent
        ua = UserAgent()
        user_agent = ua.random

        # Set up basic chrome profile
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument(f'user-agent={user_agent}')
        chrome_options.add_argument("start-maximized")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        caps = chrome_options.to_capabilities()

        # Start chrome driver
        self.driver = webdriver.Chrome(executable_path='./chromedriver.exe', options=chrome_options, desired_capabilities=caps)

    def scrape(self, url, data_elem='primary'):
        """
        Navigate to desired URL and return source HTML.

        :param url: URL to scrape source HTML from
        :param data_elem: DOM element to use for WebDriverWait
        :return: Source HTML of web page
        """
        # Make GET request TODO need to catch timeout exception and wait until wifi reconnects before resuming
        self.driver.get(url)

        # Wait for data to load
        WebDriverWait(self.driver, 10).until(ec.visibility_of_element_located((By.CLASS_NAME, data_elem)))

        return self.driver.page_source

    def close(self):
        """
        Close browser instance.
        :return: None
        """
        self.driver.quit()


class UrlBuilder:
    # https://www.asx.com.au/asx/share-price-research/company/4DS/statistics/shares
    # https://www.asx.com.au/asx/research/listedCompanies.do
    def __init__(self, base='https://www.asx.com.au/asx'):
        self.base = base

    def build_url(self, routes, base=None):
        url = self.base if not base else base
        for route in routes:
            url += '/' + route
        return url

    @staticmethod
    def ticker_route(ticker):
        return 'share-price-research/company/' + ticker


class StatisticsUrl(UrlBuilder):
    def url(self, ticker):
        return self.build_url([self.ticker_route(ticker), 'statistics/shares'])


class DetailsUrl(UrlBuilder):
    def url(self, ticker):
        return self.build_url([self.ticker_route(ticker), 'details'])


class ListedCompaniesUrl(UrlBuilder):
    def url(self, _):
        return self.build_url(['research/listedCompanies.do'])


class _DataFetcher:
    def __init__(self):
        self.scraper = Scraper()
        self.url_obj = None

    def parse(self, soup):
        data = dict()
        return data

    def fetch(self, ticker):
        url = self.url_obj.url(ticker)
        html = self.scraper.scrape(url)
        return self.parse(html)


class StatisticsFetcher(_DataFetcher):
    def __init__(self):
        super().__init__()
        self.url_obj = StatisticsUrl()

    def parse(self, html):
        data = dict()
        tables_list = pandas.read_html(html)
        stats_table = tables_list[0]
        data['shares issued'] = stats_table.iloc[8, 1]
        return data


class DetailsFetcher(_DataFetcher):
    def __init__(self):
        super().__init__()
        self.url_obj = DetailsUrl()

    def parse(self, html):
        data = dict()
        soup = BeautifulSoup(html, 'html.parser')
        try:
            data['sector'] = soup.find('div', attrs={'class': 'company-subscript ng-binding', 'ng-bind': 'company.sector_name'}).contents[0]
        except AttributeError:
            data['sector'] = 'LIC'  # TODO this is just a guess, based on how asx website behaves

        tables_list = pandas.read_html(html)
        stats_table = tables_list[0]
        data['url'] = stats_table.iloc[5, 1]
        return data


if __name__ == '__main__':
    df = DetailsFetcher()
    df.fetch('4DS')
