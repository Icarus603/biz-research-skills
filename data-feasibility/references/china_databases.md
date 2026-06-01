# China Academic & Financial Databases

## Commercial Databases (Subscription Required)

### Financial / Capital Markets
| Database | Coverage | Key Variables | Access |
|----------|---------|--------------|--------|
| CSMAR (国泰安) | A股1990+, 上市公司财务、股价、公司治理 | ROA, Tobin's Q, ownership structure, analyst forecasts | Most Chinese universities |
| WIND (万得) | 实时+历史金融数据，宏观、债券、期货 | All financial markets | Commercial license |
| RESSET (锐思) | A/B股, 基金, 宏观 | Similar to CSMAR | Universities |
| CNRDS (中国研究数据服务平台) | 文本数据(年报/公告/新闻)、专利、ESG | MD&A text, patent citations, green bond | ~50 universities |
| Choice (东方财富) | A股, ETF, 债券 | Real-time data | Commercial |

### Patent / Innovation
| Database | Coverage | Key Variables |
|----------|---------|--------------|
| CNRDS 专利 | CNIPA patents 1985+ | IPC class, citations, inventor location |
| Patsnap (智慧芽) | Global patents incl. CN | Citation network, technology classifications |
| SIPO/CNIPA官网 | Free partial access | Basic patent metadata |
| WIPO PatStat | Global, annual release | Bilateral citation, family |

### Industry / Firm
| Database | Coverage | Key Variables |
|----------|---------|--------------|
| CCER (色诺芬) | A股公司治理 | Board composition, compensation |
| Annual Survey of Industrial Firms (规上工业企业调查) | 1998-2013, ~300k firms/year | Output, employment, capital, TFP | Access via researchers who have it |
| NBS firm-level data | Various surveys | Restricted, apply directly |

### Labor / Household
| Database | Coverage | Key Variables |
|----------|---------|--------------|
| CFPS (中国家庭追踪调查) | 2010+, biennial | Income, education, health, migration | Free registration at Peking Univ |
| CHFS (中国家庭金融调查) | 2011+, biennial | Wealth, financial assets, housing | Free registration at SWUFE |
| CGSS (中国综合社会调查) | 2003+, annual/biennial | Social attitudes, employment, income | Free registration at Renmin |
| CHARLS (中国健康与养老追踪调查) | 2011+, biennial | Elderly, health, pension | Free registration at Peking Univ |
| RUMiC (中国城乡移民调查) | 2008-2009 | Rural-urban migrants | Publicly available |

### Regional / Macro
| Database | Coverage | Key Variables |
|----------|---------|--------------|
| China Statistical Yearbook (中国统计年鉴) | Province/city level, 1978+ | GDP, population, FDI | NBS website, free |
| CEIC | Macro time series | GDP, CPI, trade | Subscription |
| GTA 地理空间 | Satellite, nightlight, land use | NDVI, NTL, POI | CNRDS subset |

---

## International Databases (Often Accessible)

| Database | Coverage | Typical Use |
|----------|---------|------------|
| Compustat | US/Global firms | Benchmark comparison |
| Amadeus/Bureau van Dijk | European firms | Cross-country |
| World Bank WDI | Country-level | Controls |
| IMF IFS | Macro/financial | Controls |
| OECD STAN | Industry-level | Trade/technology |
| UN Comtrade | Bilateral trade | Trade flows |
| PATSTAT (EPO) | Global patents | Innovation |
| Semantic Scholar / OpenAlex | Publications | Research output |

---

## Scraping-Accessible Public Sources

| Source | Data | Method | Legal Risk |
|--------|------|--------|-----------|
| 国家企业信用信息公示系统 | Firm registration, shareholders | Scrapy/Selenium | Low (public) |
| 天眼查/企查查 | Firm info, legal cases | API (paid) / scrape | Medium (ToS) |
| CNIPA (国家知识产权局) | Patent full text | Bulk download available | Low |
| CNINF (巨潮资讯) | A股公告, 年报 PDF | Direct download | Low |
| NBS (国家统计局) | Aggregated stats | Web scrape | Low |
| 裁判文书网 | Court cases | Scrape (now restricted) | Medium |
| 微博/微信公众号 | Social media text | API (restricted) / scrape | Medium-High |
| 职位招聘 (51job/BOSS直聘) | Job postings, skill demand | Scrape | Medium |
| 学术论文引用 (CNKI) | Publication metadata | Scrape (restricted) | High |
