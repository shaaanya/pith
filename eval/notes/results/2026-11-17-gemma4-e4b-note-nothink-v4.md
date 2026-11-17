# note-nothink-v4 (gemma4:e4b)

```json
{
 "variant": "note-nothink-v4",
 "model": "gemma4:e4b",
 "cases": 14,
 "mean_recall": 0.986,
 "blocking": 2,
 "commentary_total": 0,
 "invented_number_cases": 1,
 "mean_words": 124,
 "total_calls": 13,
 "total_seconds": 251.1
}
```

## twitch_reel  recall 1.0  blocking=False  40.3s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Twitch entry-level Payments software engineer role preparation plan

## Steps

1. Find the tech stack by looking at older Twitch job postings and engineering blog articles.
2. Learn payments fundamentals, which are idempotency and database transactions.
3. Do the Tour of Go.
4. Read Marc Brooker's writing on DynamoDB and Aurora DSQL.
5. Practice system design on Devmaxx every morning, focusing on the database questions.
6. Build a fishing tournament manager using Lambda, DynamoDB, SQS, and Step Functions.

## Facts

- Twitch posted an entry-level Payments software engineer role with a salary range of $127K-$185K.
- The tech stack includes Go, DynamoDB, Lambda, SQS, and Step Functions.
- Chapter 7 of Designing Data-Intensive Applications covers idempotency and database transactions.

## postgres_noisy_transcript  recall 1.0  blocking=False  19.3s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Postgres performance fixes

1. When creating an index, use CREATE INDEX CONCURRENTLY to prevent locking the table for writes.
2. Always run EXPLAIN (ANALYZE, BUFFERS) before and after changes to see actual numbers.
3. Stop using OFFSET pagination because it gets slower the deeper you go.
4. Use keyset pagination with the format WHERE id > $last_id ORDER BY id LIMIT 50.

## podcast_brief_mention_intent  recall 1.0  blocking=False  19.4s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

**Why saved:** Saved for the Claude Code skill mentioned in the middle

Agent workflows, code review habits, and burnout

## Relevant to why you saved this

- There is a Claude Code skill called systematic-debugging.

## Steps

1. systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.
2. They agree to cap work in progress at 3 tasks.

## Facts

- The show discusses shipping faster with coding agents.
- Marcus blocks mornings for deep work and does no meetings before noon.
- They discuss how on call rotations should change when agents ship code at night.

## Claims

- Dana thinks the biggest win with coding agents is fewer context switches.
- Marcus disagrees and states review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- Dana says burnout is the real risk with agents because the pace never drops.

## podcast_brief_mention_no_intent  recall 0.8  blocking=False  14.3s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Agent workflows, code review habits, and burnout

## Steps

1. systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.
2. Marcus blocks mornings for deep work and does no meetings before noon.
3. Dana and Marcus agreed to cap work in progress at 3 tasks.

## Facts

- The conversation is about shipping faster with coding agents.
- A Claude Code skill called systematic-debugging exists.
- They discussed how on call rotations should change when agents ship code at night.

## Claims

- Dana thinks the biggest win with coding agents is fewer context switches.
- Marcus disagrees and states that review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- Dana stated she only found systematic-debugging last week.
- Dana says burnout is the real risk with agents because the pace never drops.

## Resources

- Marcus recommends the book Four Thousand Weeks by Oliver Burkeman for thinking about limits.

## docker_tutorial  recall 1.0  blocking=True  14.9s / 1 calls
missing(critical)=[] forbidden=[] invented=['11'] commentary=0

Deploy a Flask app on a VPS with Docker

1. Create a Dockerfile starting from python 3.12 slim.
2. Copy requirements.txt.
3. Run pip install no cache dir.
4. Copy the app and set the command to gunicorn bound to 0.0.0.0 port 8000 with app:app.
5. Build it with docker build -t flaskapp .
6. Run it with docker run -d -p 80:8000 --env-file .env --restart unless stopped flaskapp.
7. The .env file needs DATABASE_URL and SECRET_KEY.
8. Never commit that file and add it to .gitignore.
9. If the container exits, check docker logs flaskapp.
10. For https, put caddy in front, and it gets the certificate automatically.
11. The caddyfile is just your domain and reverse_proxy localhost:8000.

## opinion_essay  recall 1.0  blocking=False  27.5s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Developer productivity metrics analysis

## Steps

1. DORA metrics should be tracked per team, never per individual.

## Facts

- At one company, commit counts per developer rose 40% within a quarter after being added to a dashboard.
- At that company, shipped features per quarter fell from 11 to 8.
- A one line fix to a payment bug can matter more than a month of churn.
- Critics reply that some quantitative signal is needed for management.
- The author suggests DORA metrics instead.
- DORA metrics include deployment frequency, lead time for changes, change failure rate, and time to restore service.

## Claims

- Counting commits to measure developer productivity is a mistake because of Goodhart's law.
- Developers split work into tiny commits and avoided hard refactors that produce a single large change.
- The first argument is that commits measure activity, not value.
- The metric punishes collaboration because pairing and review produce no commits for the reviewer.
- The third argument is that the metric hides the real constraint, which in the described cases was waiting time between review and deploy, a median of 3 days.

## Caveats

- DORA metrics still carry the risk of gaming.

## news_numbers  recall 1.0  blocking=False  21.4s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Harbour Ferries MV Linnet suspension

## Facts

- Harbour Ferries suspended all sailings on the Kestrel route on Tuesday, 14 October.
- The suspension occurred after an inspection found cracks in the hull of the MV Linnet.
- The company confirmed 212 passengers were on board when the cracks were reported on 9 October.
- Nobody was hurt during the incident involving the MV Linnet.
- The MV Linnet was built in 1998.
- The Linnet carries up to 340 passengers.
- Transport minister Priya Anand said the suspension would last at least 3 weeks.
- Transport minister Priya Anand stated that the ferry operator would receive no compensation for lost fares.
- Harbour Ferries denied the allegation, saying the 2023 reports found only cosmetic wear.
- Replacement buses will run every 20 minutes from Wednesday.
- The cost of replacement buses is 4.50 pounds per trip, which is the same as the ferry fare.

## Claims

- A union representative, Tom Reyes, alleged that two earlier inspection reports in 2023 had flagged corrosion and were not acted on.

## Caveats

- The claim regarding the 2023 inspection reports has not been verified.

## web_table_article  recall 1.0  blocking=False  19.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Message Queue Selection Criteria

## Steps

1. Pick Apache Kafka only if consumers must re-read history or if more than 100,000 messages per second are needed.
2. Pick Amazon SQS FIFO when order matters per customer.

## Facts

- The decision for most teams comes down to ordering guarantees and operational cost.
- Amazon SQS Standard has best effort ordering, no replay, a max message size of 256 KB, and no operational cost.
- Amazon SQS FIFO has strict per group ordering, no replay, a max message size of 256 KB, and no operational cost.
- Apache Kafka has strict per partition ordering, replay capability, a default max message size of 1 MB, and a high operational cost.
- RabbitMQ has per queue ordering, no replay, a max message size of 128 MB, and a medium operational cost.

## Claims

- A managed queue is recommended as a starting point unless replay is needed.

## Caveats

- Avoid RabbitMQ lazy queues for payloads near the 128 MB limit because memory pressure causes stalls.

## plain_note  recall 1.0  blocking=False  0.0s / 0 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Dentist Thu 3pm, bring insurance card. Ask about the night guard. Pick up Mira's inhaler refill before 6.

## promo_filler_reel  recall 1.0  blocking=False  12.6s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

My 5am routine

## Steps

1. For the first hour, there is no phone use.
2. 500 ml of water is drunk.
3. 10 minutes of mobility is done.
4. For 45 minutes, writing is done at six.

## Facts

- The routine involves waking up at five.
- A cold shower is optional.

## Claims

- The research on cold showers is weak.

## incomplete_list  recall 1.0  blocking=False  10.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Ten habits of great engineers

## Steps

1. One habit is to write design docs before code.
2. Two habits is to read the code of the tools they use.
3. Three habits is to delete code happily.
4. Four habits is to ask what problem are we solving before how.

## Facts

- There are ten habits of great engineers.

**Limits:** The remaining six habits of great engineers are not provided.

## ocr_config_screenshot  recall 1.0  blocking=False  14.2s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

**Why saved:** Settings to copy for the nginx rate limit

Nginx rate limit settings

## Steps

1. In the server block, the location /api/ uses limit_req zone=api burst=10 nodelay.
2. In the location /api/ block, limit_req_status 429 is set.
3. To reload nginx, the command sudo nginx -s reload must be executed.

## Facts

- The zone named api is defined with a size of 10m and a rate of 5r/s.
- The size 10m in the zone comment approximates 160k IPs.

## Source text, exact
```
nginx.conf
http {
  limit_req_zone $binary_remote_addr zone=api:10m rate=5r/s;
  server {
    location /api/ {
      limit_req zone=api burst=10 nodelay;
      limit_req_status 429;
    }
  }
}
# 10m zone ~ 160k IPs
reload: sudo nginx -s reload
```

## paper_results  recall 1.0  blocking=False  20.1s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

WindowSparse paper abstract and limitations

## Facts

- On the LongDocQA benchmark, WindowSparse reaches 71.4 F1.
- Full attention reaches 68.9 F1 on the LongDocQA benchmark.
- WindowSparse uses 3.1x less memory at 16k tokens.
- Table 2 shows full attention memory at 16k tokens is 38.2 GB.
- Table 2 shows WindowSparse memory at 16k tokens is 12.3 GB.
- Training used 64 A100 GPUs for 9 days.
- WindowSparse underperforms on tasks requiring long-range exact copy.
- WindowSparse drops to 41.0 F1 on the SyntheticCopy task.
- Full attention reaches 88.5 F1 on the SyntheticCopy task.
- The evaluation did not proceed beyond 32k tokens.

## Claims

- The improvement over full attention is within one standard deviation on three of the 5 tasks.

## Definitions

- WindowSparse is a sparse attention pattern that combines local windows of 512 tokens with 8 global tokens per layer.

## correction_in_talk  recall 1.0  blocking=True  16.5s / 1 calls
missing(critical)=[] forbidden=['had 6 nodes'] invented=[] commentary=0

Sharding implementation lesson

## Steps

1. The team switched to sharding by document id hash.
2. The team moved to 12 nodes after the switch.

## Facts

- The search cluster initially had 6 nodes.
- Sharding by customer handled 2,000 queries per second.
- One huge customer caused one shard to become hot.
- P99 latency hit 900 ms due to the hot shard.
- The original cluster had 8 nodes, not 6.
- After the switch, p99 dropped to 120 ms.

## Claims

- Sharding by customer was initially thought to be the answer.
- The lesson is do not shard on a key whose distribution you do not control.
