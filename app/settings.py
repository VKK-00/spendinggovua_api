from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Settings:
    base_url: str = "https://spending.gov.ua"
    browser_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    browser_headless: bool = False
    browser_timeout_ms: int = 90_000
    reports_page_size: int = 1_000
    cache_ttl_seconds: int = 1_800

    @property
    def login_page_url(self) -> str:
        return f"{self.base_url}/login"

    def disposer_reports_page(self, edrpou: str) -> str:
        return f"{self.base_url}/new/en/disposers/{edrpou}/reports"

    def reports_page_api(self, edrpou: str, sign_status: str, size: int | None = None) -> str:
        page_size = size or self.reports_page_size
        return (
            f"{self.base_url}/portal-api/v2/api/reports/{edrpou}/page"
            f"?page=0&signStatus={sign_status}&size={page_size}"
        )

    def report_details_api(self, edrpou: str, report_id: int) -> str:
        return f"{self.base_url}/portal-api/v2/api/reports/{edrpou}/{report_id}"

    def report_details_page(self, edrpou: str, report_id: int) -> str:
        return f"{self.base_url}/new/disposers/{edrpou}/reports/{report_id}"

    @property
    def periods_api(self) -> str:
        return f"{self.base_url}/portal-api/v2/api/reports/periods/"

    @property
    def report_types_api(self) -> str:
        return f"{self.base_url}/portal-api/v2/api/reports/report_types/"
