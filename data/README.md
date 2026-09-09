# Discord Analytics Dataset (Synthetic)

This dataset contains realistic synthetic data for multiple Discord servers, designed for analytics and modeling tasks.

## Files Description

- **servers.csv**: Metadata for each Discord server (e.g., name, creation date, region, premium tier, etc.)
- **channels.csv**: List of all channels (text and voice) per server with attributes (NSFW, rate limit, etc.)
- **members.csv**: User profiles per server including join date, last active, roles, message count, voice minutes.
- **daily_stats.csv**: Daily aggregated metrics per server: total messages, new members, active members, total members.
- **channel_daily_stats.csv**: Daily message counts and active users per text channel.
- **messages_sample.csv**: A sample of individual messages (up to 5000) with content, reactions, attachments, etc.

## Column Descriptions

Detailed column descriptions are provided in the accompanying `data_dictionary.txt`.

## Usage

This dataset is purely synthetic and does not contain any real user data. It can be used for:
- Time-series forecasting (messages, members)
- User engagement analysis
- Community growth modeling
- NLP on message content
- Social network analysis

## Generation Details

- Number of servers: 10
- Time period: last 180 days
- Members per server: 50-500
- Generated with Python using Faker, NumPy, and Pandas.

## License

CC0 1.0 Universal (Public Domain)
