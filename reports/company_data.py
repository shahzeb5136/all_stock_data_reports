"""
Fallback company data for the top 20 dip tickers.
Used when yfinance is unavailable.
Data is approximate and based on publicly available information.
"""

COMPANY_DATA = {
    "SHOP": {
        "name": "Shopify Inc.",
        "sector": "Technology",
        "industry": "E-Commerce Software",
        "market_cap": 125e9,
        "pe_ratio": 75.2,
        "forward_pe": 55.0,
        "avg_volume": 7_800_000,
        "52w_high": 115.50,
        "52w_low": 52.80,
        "description": (
            "Shopify Inc. provides a cloud-based, multi-channel commerce platform for small and "
            "medium-sized businesses. The company's software allows merchants to set up online stores, "
            "manage inventory, process payments, and fulfill orders. Shopify also offers point-of-sale "
            "solutions, shipping and logistics services, and access to business financing through "
            "Shopify Capital. Founded in 2006 and headquartered in Ottawa, Canada, the company "
            "serves millions of merchants in over 175 countries."
        ),
    },
    "ROKU": {
        "name": "Roku, Inc.",
        "sector": "Technology",
        "industry": "Streaming / Connected TV",
        "market_cap": 10e9,
        "pe_ratio": None,
        "forward_pe": 45.0,
        "avg_volume": 6_200_000,
        "52w_high": 90.20,
        "52w_low": 50.30,
        "description": (
            "Roku, Inc. operates a streaming platform that connects users to a wide range of streaming "
            "content. The company manufactures streaming players and licenses its operating system to "
            "smart TV manufacturers. Roku generates revenue primarily through advertising on its "
            "platform, content distribution fees, and hardware sales. Headquartered in San Jose, "
            "California, Roku has a large installed base of active accounts in the U.S. and is "
            "expanding internationally."
        ),
    },
    "NVDA": {
        "name": "NVIDIA Corporation",
        "sector": "Technology",
        "industry": "Semiconductors",
        "market_cap": 3_000e9,
        "pe_ratio": 62.5,
        "forward_pe": 35.0,
        "avg_volume": 45_000_000,
        "52w_high": 152.89,
        "52w_low": 75.61,
        "description": (
            "NVIDIA Corporation designs and sells graphics processing units (GPUs) and system-on-chip "
            "units. The company is the dominant provider of GPUs for AI training and inference workloads, "
            "data center accelerators, and gaming graphics cards. NVIDIA's CUDA platform and software "
            "ecosystem are widely used in machine learning, scientific computing, and autonomous vehicles. "
            "Founded in 1993 and headquartered in Santa Clara, California, NVIDIA has become one of the "
            "most valuable companies in the world."
        ),
    },
    "INTC": {
        "name": "Intel Corporation",
        "sector": "Technology",
        "industry": "Semiconductors",
        "market_cap": 105e9,
        "pe_ratio": None,
        "forward_pe": None,
        "avg_volume": 55_000_000,
        "52w_high": 51.28,
        "52w_low": 18.51,
        "description": (
            "Intel Corporation designs, manufactures, and sells integrated circuits and computing "
            "technologies. Historically the world's largest semiconductor maker, Intel produces CPUs "
            "for personal computers and data centers, as well as programmable chips (FPGAs) and "
            "networking components. The company is investing heavily in its foundry services business "
            "to manufacture chips for third parties. Founded in 1968 and headquartered in Santa Clara, "
            "California, Intel is navigating a significant strategic turnaround."
        ),
    },
    "RIVN": {
        "name": "Rivian Automotive, Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Electric Vehicles",
        "market_cap": 14e9,
        "pe_ratio": None,
        "forward_pe": None,
        "avg_volume": 28_000_000,
        "52w_high": 28.06,
        "52w_low": 8.26,
        "description": (
            "Rivian Automotive is an electric vehicle manufacturer focused on adventure-oriented "
            "consumer vehicles and commercial delivery vans. The company produces the R1T pickup truck "
            "and R1S SUV, and has a large contract to build delivery vans for Amazon. Rivian operates "
            "its own manufacturing plant in Normal, Illinois, and is building a second facility in "
            "Georgia. The company is pre-profit and investing heavily in scaling production."
        ),
    },
    "AMD": {
        "name": "Advanced Micro Devices, Inc.",
        "sector": "Technology",
        "industry": "Semiconductors",
        "market_cap": 200e9,
        "pe_ratio": 45.3,
        "forward_pe": 28.0,
        "avg_volume": 42_000_000,
        "52w_high": 227.30,
        "52w_low": 120.83,
        "description": (
            "Advanced Micro Devices (AMD) designs high-performance CPUs, GPUs, and adaptive computing "
            "products. The company competes directly with Intel in PC and server processors and with "
            "NVIDIA in data center GPUs for AI workloads. AMD's products are manufactured by TSMC. "
            "With the acquisitions of Xilinx and Pensando, AMD expanded into FPGAs and data processing "
            "units. Headquartered in Santa Clara, California."
        ),
    },
    "LCID": {
        "name": "Lucid Group, Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Electric Vehicles",
        "market_cap": 7e9,
        "pe_ratio": None,
        "forward_pe": None,
        "avg_volume": 32_000_000,
        "52w_high": 7.34,
        "52w_low": 1.93,
        "description": (
            "Lucid Group is a luxury electric vehicle manufacturer known for its Lucid Air sedan, "
            "which features industry-leading range and performance. The company also develops battery "
            "and powertrain technology. Backed by Saudi Arabia's Public Investment Fund, Lucid operates "
            "a factory in Casa Grande, Arizona, and is expanding into international markets including "
            "Saudi Arabia and Europe. The company is pre-profit and working toward production scale."
        ),
    },
    "BA": {
        "name": "The Boeing Company",
        "sector": "Industrials",
        "industry": "Aerospace & Defense",
        "market_cap": 130e9,
        "pe_ratio": None,
        "forward_pe": 35.0,
        "avg_volume": 8_500_000,
        "52w_high": 267.54,
        "52w_low": 137.03,
        "description": (
            "The Boeing Company is one of the world's largest aerospace manufacturers and defense "
            "contractors. The company designs and builds commercial jetliners (737, 787, 777X), "
            "military aircraft, satellites, and space systems. Boeing has faced challenges related to "
            "production quality and safety, particularly with the 737 MAX program. Headquartered in "
            "Arlington, Virginia, Boeing also provides services and support for its global fleet."
        ),
    },
    "AMZN": {
        "name": "Amazon.com, Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Internet Retail / Cloud Computing",
        "market_cap": 2_100e9,
        "pe_ratio": 60.5,
        "forward_pe": 35.0,
        "avg_volume": 42_000_000,
        "52w_high": 242.52,
        "52w_low": 151.61,
        "description": (
            "Amazon.com is a multinational technology company operating the world's largest online "
            "marketplace, a leading cloud computing platform (AWS), and a growing digital advertising "
            "business. The company also produces consumer electronics (Kindle, Echo, Fire TV), operates "
            "physical grocery stores, and produces original video content through Prime Video. "
            "Headquartered in Seattle, Washington, Amazon is one of the most valuable companies globally."
        ),
    },
    "CRM": {
        "name": "Salesforce, Inc.",
        "sector": "Technology",
        "industry": "Application Software / CRM",
        "market_cap": 260e9,
        "pe_ratio": 48.2,
        "forward_pe": 28.0,
        "avg_volume": 6_500_000,
        "52w_high": 369.00,
        "52w_low": 212.00,
        "description": (
            "Salesforce is the world's leading provider of cloud-based customer relationship management "
            "(CRM) software. The company's platform includes tools for sales, service, marketing, "
            "commerce, and analytics. Through acquisitions of Slack, Tableau, and MuleSoft, Salesforce "
            "has expanded into workplace collaboration, data visualization, and integration. The "
            "company is increasingly focused on AI with its Einstein and Agentforce platforms. "
            "Headquartered in San Francisco, California."
        ),
    },
    "NKE": {
        "name": "NIKE, Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Footwear & Apparel",
        "market_cap": 115e9,
        "pe_ratio": 23.5,
        "forward_pe": 28.0,
        "avg_volume": 11_000_000,
        "52w_high": 123.39,
        "52w_low": 70.75,
        "description": (
            "NIKE, Inc. is the world's largest athletic footwear and apparel company. The company "
            "designs, develops, and markets shoes, clothing, equipment, and accessories under the Nike, "
            "Jordan, and Converse brands. Nike sells through its own retail stores and website as well "
            "as wholesale partners globally. The company is navigating a strategic reset focused on "
            "innovation and brand heat. Headquartered in Beaverton, Oregon."
        ),
    },
    "PFE": {
        "name": "Pfizer Inc.",
        "sector": "Healthcare",
        "industry": "Pharmaceuticals",
        "market_cap": 155e9,
        "pe_ratio": 18.5,
        "forward_pe": 10.0,
        "avg_volume": 38_000_000,
        "52w_high": 31.54,
        "52w_low": 24.48,
        "description": (
            "Pfizer Inc. is a global pharmaceutical and biotechnology corporation that discovers, "
            "develops, manufactures, and markets medicines, vaccines, and consumer health products. "
            "Known for its COVID-19 vaccine developed with BioNTech, Pfizer has a broad pipeline "
            "spanning oncology, immunology, rare diseases, and anti-infectives. The company recently "
            "acquired Seagen to bolster its oncology portfolio. Headquartered in New York City."
        ),
    },
    "ZM": {
        "name": "Zoom Video Communications, Inc.",
        "sector": "Technology",
        "industry": "Communications Software",
        "market_cap": 20e9,
        "pe_ratio": 25.0,
        "forward_pe": 15.0,
        "avg_volume": 4_200_000,
        "52w_high": 92.96,
        "52w_low": 55.07,
        "description": (
            "Zoom Video Communications provides a unified communications platform centered on video "
            "conferencing. The company's products include Zoom Meetings, Zoom Phone, Zoom Rooms, "
            "Zoom Contact Center, and AI-powered features like Zoom AI Companion. After explosive "
            "growth during the pandemic, Zoom is repositioning as a broader workplace collaboration "
            "platform. Headquartered in San Jose, California."
        ),
    },
    "LYFT": {
        "name": "Lyft, Inc.",
        "sector": "Technology",
        "industry": "Ride-Sharing / Mobility",
        "market_cap": 6e9,
        "pe_ratio": None,
        "forward_pe": 20.0,
        "avg_volume": 15_000_000,
        "52w_high": 20.98,
        "52w_low": 9.30,
        "description": (
            "Lyft, Inc. operates a peer-to-peer ride-sharing platform in the United States and Canada. "
            "The company's app connects riders with drivers and also offers bike and scooter rentals "
            "in select markets. Lyft competes primarily with Uber and has been focused on improving "
            "profitability and operational efficiency. Headquartered in San Francisco, California."
        ),
    },
    "UNH": {
        "name": "UnitedHealth Group Incorporated",
        "sector": "Healthcare",
        "industry": "Health Insurance / Managed Care",
        "market_cap": 480e9,
        "pe_ratio": 32.0,
        "forward_pe": 18.0,
        "avg_volume": 4_000_000,
        "52w_high": 630.73,
        "52w_low": 436.38,
        "description": (
            "UnitedHealth Group is the largest health insurance company in the United States by revenue. "
            "The company operates through two main segments: UnitedHealthcare (health benefits) and "
            "Optum (health services including pharmacy, care delivery, and analytics). UnitedHealth "
            "serves employers, individuals, Medicare, and Medicaid beneficiaries. Headquartered in "
            "Minnetonka, Minnesota."
        ),
    },
    "AAPL": {
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "market_cap": 3_400e9,
        "pe_ratio": 33.0,
        "forward_pe": 30.0,
        "avg_volume": 55_000_000,
        "52w_high": 260.10,
        "52w_low": 164.08,
        "description": (
            "Apple Inc. designs, manufactures, and markets smartphones (iPhone), personal computers "
            "(Mac), tablets (iPad), wearables (Apple Watch, AirPods), and services (App Store, Apple "
            "Music, iCloud, Apple TV+, Apple Pay). The company's ecosystem of hardware, software, and "
            "services creates strong customer loyalty. Apple is the world's most valuable public company "
            "by market capitalization. Headquartered in Cupertino, California."
        ),
    },
    "NFLX": {
        "name": "Netflix, Inc.",
        "sector": "Communication Services",
        "industry": "Streaming Entertainment",
        "market_cap": 380e9,
        "pe_ratio": 50.0,
        "forward_pe": 35.0,
        "avg_volume": 6_000_000,
        "52w_high": 1028.00,
        "52w_low": 543.22,
        "description": (
            "Netflix, Inc. is the world's leading subscription streaming service, offering a wide "
            "variety of TV series, films, documentaries, and games across a range of genres and "
            "languages. The company produces its own original content and licenses titles from studios. "
            "Netflix has introduced an ad-supported tier and cracked down on password sharing to drive "
            "growth. Headquartered in Los Gatos, California, the company serves over 280 million "
            "subscribers worldwide."
        ),
    },
    "SNAP": {
        "name": "Snap Inc.",
        "sector": "Communication Services",
        "industry": "Social Media / Messaging",
        "market_cap": 19e9,
        "pe_ratio": None,
        "forward_pe": 40.0,
        "avg_volume": 20_000_000,
        "52w_high": 17.90,
        "52w_low": 8.28,
        "description": (
            "Snap Inc. is a technology and social media company that operates Snapchat, a camera and "
            "messaging application. The platform is known for its disappearing messages, augmented "
            "reality lenses, Stories feature, and Discover content. Snap generates revenue primarily "
            "through advertising. The company also develops Spectacles AR glasses and the My AI "
            "chatbot. Headquartered in Santa Monica, California."
        ),
    },
    "GOOGL": {
        "name": "Alphabet Inc.",
        "sector": "Communication Services",
        "industry": "Internet Content & Information",
        "market_cap": 2_200e9,
        "pe_ratio": 26.0,
        "forward_pe": 22.0,
        "avg_volume": 25_000_000,
        "52w_high": 207.05,
        "52w_low": 150.22,
        "description": (
            "Alphabet Inc. is the parent company of Google, the world's dominant search engine and "
            "digital advertising platform. The company also operates YouTube, Google Cloud, Android, "
            "Chrome, and hardware products (Pixel phones, Nest devices). Alphabet invests in emerging "
            "technologies through its Other Bets segment, including Waymo (autonomous driving) and "
            "Verily (life sciences). Headquartered in Mountain View, California."
        ),
    },
    "SPOT": {
        "name": "Spotify Technology S.A.",
        "sector": "Communication Services",
        "industry": "Music Streaming",
        "market_cap": 80e9,
        "pe_ratio": 95.0,
        "forward_pe": 50.0,
        "avg_volume": 3_200_000,
        "52w_high": 510.00,
        "52w_low": 275.00,
        "description": (
            "Spotify Technology is the world's largest music streaming service by number of subscribers. "
            "The platform offers on-demand access to a vast library of songs, podcasts, and audiobooks. "
            "Spotify operates both a free ad-supported tier and a premium subscription service. The "
            "company has invested heavily in podcasting and is expanding into audiobooks and AI-driven "
            "personalization. Headquartered in Stockholm, Sweden, with offices globally."
        ),
    },
}
