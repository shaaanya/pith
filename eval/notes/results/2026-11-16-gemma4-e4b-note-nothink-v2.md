# note-nothink-v2 (gemma4:e4b)

```json
{
 "variant": "note-nothink-v2",
 "model": "gemma4:e4b",
 "cases": 14,
 "mean_recall": 0.915,
 "blocking": 3,
 "commentary_total": 0,
 "invented_number_cases": 0,
 "mean_words": 132,
 "total_calls": 13,
 "total_seconds": 238.7
}
```

## twitch_reel  recall 1.0  blocking=False  18.7s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

30-day prep plan for an entry-level Payments software engineer role, by a career creator

## Steps

1. Figure out the technology stack by looking at older Twitch job postings and their engineering blog.
2. Learn the payments fundamentals, specifically idempotency and database transactions, using Chapter 7 of Designing Data-Intensive Applications.
3. Do the Tour of Go.
4. Read Marc Brooker's writings on DynamoDB and Aurora DSQL.
5. Practice system design every morning on Devmaxx, focusing on the database questions.
6. Build a fishing tournament manager using Lambda, DynamoDB, SQS, and Step Functions.

## Facts

- Twitch posted an entry-level Payments software engineer role with a salary range of $127K-$185K.
- The technology stack includes Go, DynamoDB, Lambda, SQS, and Step Functions.

## postgres_noisy_transcript  recall 1.0  blocking=False  18.7s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Postgres performance fixes, by an expert

1. When creating an index, use CREATE INDEX CONCURRENTLY so that writes are not blocked.
2. Always run EXPLAIN (ANALYZE, BUFFERS) before and after changes to see actual numbers instead of guesses.
3. Stop using OFFSET pagination because it gets slower the deeper you go.
4. Use keyset pagination, which uses the query WHERE id > $last_id ORDER BY id LIMIT 50.

## podcast_brief_mention_intent  recall 1.0  blocking=False  18.4s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

**Why saved:** Saved for the Claude Code skill mentioned in the middle

Agent workflows, code review habits, and burnout discussion, by a show host

## Relevant to why you saved this

- One change in debugging is a Claude Code skill called systematic-debugging.

## Steps

1. systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.
2. The participants agree to cap work in progress at three tasks.

## Facts

- The show discusses shipping faster with coding agents.
- Dana thinks the biggest win with coding agents is fewer context switches.
- Marcus disagrees, stating that review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- Marcus blocks mornings for deep work and has no meetings before noon.
- Dana says burnout is the real risk with agents because the pace never drops.
- They discuss how on call rotations should change when agents ship code at night.

## Resources

- Four Thousand Weeks by Oliver Burkeman

## podcast_brief_mention_no_intent  recall 1.0  blocking=False  17.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Discussion on shipping faster with coding agents, by an unspecified speaker

## Steps

1. They agreed to cap work in progress at three tasks.

## Facts

- The topic discussed includes coding agents, agent workflows, code review habits, and burnout.
- A Claude Code skill called systematic-debugging forces an agent to reproduce a bug and write down a hypothesis before touching any code.
- Marcus blocks mornings for deep work and avoids meetings before noon.
- They also discussed how on call rotations should change when agents ship code at night.

## Claims

- Dana thinks the biggest win regarding coding agents is fewer context switches, not speed.
- Marcus disagrees, claiming that review time merely moves to a different place.
- Dana says that small pull requests still matter because reviewers still read linearly.
- Dana says that burnout is the real risk with agents because the pace never drops.

## Resources

- Four Thousand Weeks by Oliver Burkeman is recommended for thinking about limits.

## docker_tutorial  recall 0.55  blocking=True  19.0s / 1 calls
missing(critical)=['docker build -t flaskapp .', '-p 80:8000', '--env-file .env'] forbidden=[] invented=[] commentary=0

Flask app deployment on a VPS with Docker, by an unnamed instructor

1. First create a Dockerfile starting from python 3.12 slim.
2. Copy requirements.txt and run pip install no cache dir.
3. Then copy the app and set the command to gunicorn bound to 0.0.0.0 port 8000 with app colon app.
4. Build it with docker build dash t Flask app dot.
5. Run it with docker in dash d dash p 80 colon 8000 dash dash env file dot env dash dash restart unless stopped Flask app.
6. Your dot env needs DATABASE_URL and SECRET_KEY.
7. Never commit that file and add it to dot gitignore.
8. If the container exits check docker logs Flask app.
9. For https put caddy in front it gets the certificate automatically.
10. The caddyfile is just your domain and reverse underscore proxy localhost colon 8000.

## opinion_essay  recall 1.0  blocking=False  25.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Developer productivity measurement critique, by an unnamed author

## Facts

- At one company, commit counts per developer rose 40% within a quarter after they were added to a dashboard.
- At that same company, shipped features per quarter fell from 11 to 8.
- The real constraint in the described cases was waiting time between review and deploy, which had a median of 3 days.
- DORA metrics are deployment frequency, lead time for changes, change failure rate, and time to restore service.

## Claims

- Counting commits to measure developer productivity is a mistake because of Goodhart's law.
- Developers at the company split work into tiny commits and avoided hard refactors that produce a single large change.
- The author's first argument is that commits measure activity, not value.
- A one line fix to a payment bug can matter more than a month of churn.
- The author's second argument is that the metric punishes collaboration.
- Pairing and review produce no commits for the reviewer, which is why the metric is criticized.
- The author's third argument is that the metric hides the real constraint.
- Critics reply that some quantitative signal is needed for management.
- The author concedes the need for quantitative signals and suggests DORA metrics instead.
- The author notes that DORA metrics should be tracked per team, never per individual.
- The author also notes that DORA metrics still carry the risk of gaming.

## Definitions

- Goodhart's law states that once a measure becomes a target, it stops being a good measure.

## news_numbers  recall 1.0  blocking=False  17.7s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Harbour Ferries incident report, by an unstated author

## Facts

- Harbour Ferries suspended all sailings on the Kestrel route on Tuesday 14 October.
- The suspension occurred after an inspection found cracks in the hull of the MV Linnet.
- The company confirmed 212 passengers were on board when the cracks were reported on 9 October.
- Nobody was hurt when the cracks were reported.
- The Linnet was built in 1998.
- The Linnet carries up to 340 passengers.
- Transport minister Priya Anand said the suspension would last at least 3 weeks.
- Transport minister Priya Anand stated the ferry operator would receive no compensation for lost fares.
- Replacement buses will run every 20 minutes starting from Wednesday.
- The replacement bus fare costs 4.50 pounds per trip, which is the same as the ferry fare.

## Claims

- A union representative, Tom Reyes, alleged that two earlier inspection reports in 2023 had flagged corrosion and were not acted on.
- Harbour Ferries denied the allegation, stating the 2023 reports found only cosmetic wear.

## Caveats

- The claim made by Tom Reyes has not been verified.

## web_table_article  recall 1.0  blocking=False  17.5s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Message Queue Selection Criteria, by an unnamed writer

## Steps

1. Pick Kafka only if consumers must re-read history or you need more than 100,000 messages per second.
2. Pick SQS FIFO when order matters per customer.

## Facts

- For most teams, the message queue decision comes down to ordering guarantees and operational cost.
- Amazon SQS Standard provides best effort ordering, no replay, a maximum message size of 256 KB, and no operational cost.
- Amazon SQS FIFO provides strict per group ordering, no replay, a maximum message size of 256 KB, and no operational cost.
- Apache Kafka provides strict per partition ordering, has replay capabilities, a default maximum message size of 1 MB, and high operational cost.
- RabbitMQ provides per queue ordering, no replay, a maximum message size of 128 MB, and medium operational cost.

## Claims

- The recommendation is to start with a managed queue unless replay is needed.

## Caveats

- Avoid RabbitMQ lazy queues for payloads near the 128 MB limit because memory pressure causes stalls.

## plain_note  recall 1.0  blocking=False  0.0s / 0 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Dentist Thu 3pm, bring insurance card. Ask about the night guard. Pick up Mira's inhaler refill before 6.

## promo_filler_reel  recall 0.83  blocking=False  20.5s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

My 5am routine, by an unnamed person

## Steps

1. No phone is used for the first hour.
2. The speaker drinks 500 ml of water.
3. Then, ten minutes of mobility is done.
4. At six, the speaker writes for 45 minutes before anything else.

## Facts

- The speaker wakes at five.
- A cold shower is optional.

## incomplete_list  recall 1.0  blocking=False  12.9s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Ten habits of great engineers, by an unspecified person

## Steps

1. They write things down, design docs before code.
2. They read the code of the tools they use.
3. They delete code happily.
4. They ask what problem are we solving before how.

## Facts

- There are ten habits of great engineers.

**Limits:** The remaining five habits of great engineers are not provided.

## ocr_config_screenshot  recall 0.43  blocking=True  18.1s / 1 calls
missing(critical)=['limit_req_zone', 'rate=5r/s', 'zone=api:10m', 'burst=10'] forbidden=[] invented=[] commentary=0

**Why saved:** Settings to copy for the nginx rate limit

Nginx rate limiting settings, by a configuration file

## Relevant to why you saved this

1. A rate limit zone named api is defined with a size of 10m and a rate of 5r/s.

## Steps

1. Inside the server block, a location matching /api/ is configured.
2. Inside the /api/ location, the limit_req directive is set with the zone api, a burst value of 10, and nodelay.
3. The limit_req_status directive is set to 429 for the /api/ location.
4. To reload the configuration, the command sudo nginx -s reload must be executed.

## Facts

- The configuration uses the http block in nginx.conf.
- The 10m zone corresponds to approximately 160k IPs.

## paper_results  recall 1.0  blocking=False  20.0s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

WindowSparse paper abstract, by an author

- WindowSparse is a sparse attention pattern combining local windows of 512 tokens with 8 global tokens per layer.
- On the LongDocQA benchmark, WindowSparse reaches 71.4 F1.
- Full attention reaches 68.9 F1 on the LongDocQA benchmark.
- WindowSparse uses 3.1x less memory at 16k tokens compared to full attention.
- Table 2 shows that full attention uses 38.2 GB of memory at 16k tokens.
- Table 2 shows that WindowSparse uses 12.3 GB of memory at 16k tokens.
- Training utilized 64 A100 GPUs for 9 days.
- The improvement over full attention is within one standard deviation on three of the five tasks.
- WindowSparse underperforms on tasks requiring long-range exact copy, dropping to 41.0 F1 on the SyntheticCopy task.
- Full attention achieves 88.5 F1 on the SyntheticCopy task.
- The evaluation did not go beyond 32k tokens.

## correction_in_talk  recall 1.0  blocking=True  13.6s / 1 calls
missing(critical)=[] forbidden=['had 6 nodes'] invented=[] commentary=0

Sharding methodology change, by a software engineer

## Steps

1. The team switched to sharding by document id hash.

## Facts

- The initial search cluster had 6 nodes.
- Sharding by customer was found to be a mistake.
- One huge customer made one shard hot, causing p99 latency to hit 900 ms.
- The original cluster actually had 8 nodes, not 6 (This is a correction).
- After the switch, p99 dropped to 120 ms.
- The cluster moved to 12 nodes after the switch.

## Claims

- Sharding by customer was believed to be the answer as it handled 2,000 queries per second.
- The lesson is not to shard on a key whose distribution is not controlled.
