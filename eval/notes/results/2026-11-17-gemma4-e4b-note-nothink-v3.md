# note-nothink-v3 (gemma4:e4b)

```json
{
 "variant": "note-nothink-v3",
 "model": "gemma4:e4b",
 "cases": 14,
 "mean_recall": 0.941,
 "blocking": 3,
 "commentary_total": 0,
 "invented_number_cases": 1,
 "mean_words": 130,
 "total_calls": 13,
 "total_seconds": 211.6
}
```

## twitch_reel  recall 1.0  blocking=False  90.4s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Twitch entry-level Payments software engineer role preparation plan

## Steps

1. Find the tech stack by looking at older Twitch job postings and engineering blog articles.
2. Learn payments fundamentals, which are idempotency and database transactions, by reading Chapter 7 of Designing Data-Intensive Applications.
3. Complete the Tour of Go.
4. Read Marc Brooker's writing on DynamoDB and Aurora DSQL.
5. Practice system design on Devmaxx every morning, focusing on the database questions.
6. Build a fishing tournament manager using Lambda, DynamoDB, SQS, and Step Functions.

## Facts

- Twitch posted an entry-level payments software engineer role with a salary range of $127K-$185K.
- The tech stack identified is Go, DynamoDB, Lambda, SQS, and Step Functions.

## postgres_noisy_transcript  recall 0.6  blocking=True  10.5s / 1 calls
missing(critical)=['limit 50'] forbidden=[] invented=[] commentary=0

Postgres performance fixes

## Steps

1. Use keyset pagination where id is greater than the last id ORDER BY id LIMIT fifty.

## Facts

- One performance fix is to use CREATE INDEX CONCURRENTLY.
- Using CREATE INDEX CONCURRENTLY prevents locking the table for writes.
- The second performance fix is to always run EXPLAIN ANALYZE WITH BUFFERS before and after changes.
- The third performance fix is to stop using OFFSET for pagination.

## Claims

- Using EXPLAIN ANALYZE WITH BUFFERS allows viewing the actual numbers instead of guesses.
- OFFSET pagination gets slower the deeper it goes.

## podcast_brief_mention_intent  recall 1.0  blocking=False  11.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

**Why saved:** Saved for the Claude Code skill mentioned in the middle

Agent workflows, code review habits, and burnout discussion

## Relevant to why you saved this

- There is a Claude Code skill called systematic-debugging.

## Steps

1. Systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.
2. Dana and Marcus agreed to cap work in progress at three tasks.
3. Marcus recommends the book Four Thousand Weeks by Oliver Burkeman for thinking about limits.

## Facts

- The discussion is about shipping faster with coding agents.

## Claims

- Dana thinks the biggest win with coding agents is fewer context switches.
- Marcus disagrees, stating that review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- Dana found the systematic-debugging skill last week.
- Dana says burnout is the real risk with agents because the pace never drops.

## Resources

- Four Thousand Weeks by Oliver Burkeman

## podcast_brief_mention_no_intent  recall 1.0  blocking=False  9.1s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Episode 41 agent workflows, code review habits, and burnout

## Steps

1. Dana and Marcus agreed to cap work in progress at three tasks.

## Facts

- The discussion topic is shipping faster with coding agents.
- A Claude Code skill called systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.
- Marcus blocks mornings for deep work and does no meetings before noon.
- The conversation also discussed how on call rotations should change when agents ship code at night.

## Claims

- Dana thinks the biggest win with coding agents is fewer context switches.
- Marcus disagrees that fewer context switches are the biggest win, stating review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- Dana says burnout is the real risk with agents because the pace never drops.

## Resources

- Four Thousand Weeks by Oliver Burkeman is recommended by Marcus for thinking about limits.

## docker_tutorial  recall 0.91  blocking=True  12.0s / 1 calls
missing(critical)=['--env-file .env'] forbidden=[] invented=['11'] commentary=0

Deploy a Flask app on a VPS with Docker

1. Create a Dockerfile starting from python 3.12 slim.
2. Copy requirements.txt.
3. Run pip install no cache dir.
4. Copy the app and set the command to gunicorn bound to 0.0.0.0 port 8000 with app:app.
5. Build it with docker build -t flaskapp .
6. Run it with docker run -d -p 80:8000 --env file .env --restart unless stopped flaskapp.
7. The .env file needs DATABASE_URL and SECRET_KEY.
8. Never commit the .env file and add it to .gitignore.
9. If the container exits, check docker logs flaskapp.
10. For https, put caddy in front as it gets the certificate automatically.
11. The caddyfile is just your domain and reverse_proxy localhost:8000.

## opinion_essay  recall 1.0  blocking=False  15.3s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Developer productivity metrics

## Facts

- At one company, commit counts per developer rose 40% within a quarter after being added to a dashboard.
- At the same company, shipped features per quarter fell from 11 to 8.
- Developers split work into tiny commits and avoided hard refactors that produce a single large change.
- DORA metrics are deployment frequency, lead time for changes, change failure rate and time to restore service.

## Claims

- Counting commits to measure developer productivity is a mistake because of Goodhart's law, which states a measure stops being a good measure once it becomes a target.
- The first argument is that commits measure activity, not value.
- A one line fix to a payment bug can matter more than a month of churn.
- The second argument is that the metric punishes collaboration because pairing and review produce no commits for the reviewer.
- The third argument is that the metric hides the real constraint, which in the described cases was waiting time between review and deploy, a median of 3 days.
- Critics reply that some quantitative signal is needed for management.
- The author concedes the need for quantitative signal and suggests DORA metrics instead.
- The author notes that DORA metrics should be tracked per team, never per individual, and still carry the risk of gaming.

## news_numbers  recall 1.0  blocking=False  12.6s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Harbour Ferries Kestrel Route Suspension

## Facts

- Harbour Ferries suspended all sailings on the Kestrel route on Tuesday 14 October.
- The suspension was due to an inspection finding cracks in the hull of the MV Linnet.
- The company confirmed that 212 passengers were on board when the cracks were reported on 9 October.
- Nobody was hurt when the cracks were reported.
- The Linnet was built in 1998.
- The Linnet carries up to 340 passengers.
- Replacement buses will run every 20 minutes starting from Wednesday.
- Replacement bus trips cost 4.50 pounds, which is the same as the ferry fare.

## Claims

- Transport minister Priya Anand stated the suspension would last at least 3 weeks.
- Transport minister Priya Anand said the ferry operator would receive no compensation for lost fares.
- A union representative, Tom Reyes, alleged that two earlier inspection reports in 2023 flagged corrosion and were not acted on.
- Harbour Ferries denied this allegation, stating the 2023 reports found only cosmetic wear.

## Caveats

- The claim about the 2023 reports has not been verified.

## web_table_article  recall 1.0  blocking=False  10.2s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Message queue selection criteria

## Steps

1. Pick Apache Kafka only if consumers must re-read history or if more than 100,000 messages per second are needed.
2. Pick Amazon SQS FIFO when order matters per customer.

## Facts

- The decision regarding message queue selection usually focuses on ordering guarantees and operational cost.
- Amazon SQS Standard has best effort ordering, no replay, and a maximum message size of 256 KB, and zero operational cost.
- Amazon SQS FIFO has strict per group ordering, no replay, and a maximum message size of 256 KB, and zero operational cost.
- Apache Kafka has strict per partition ordering, supports replay, a default maximum message size of 1 MB, and high operational cost.
- RabbitMQ has per queue ordering, no replay, a maximum message size of 128 MB, and medium operational cost.

## Claims

- The recommendation is to start with a managed queue unless replay is required.

## Caveats

- Avoid RabbitMQ lazy queues for payloads near the 128 MB limit because memory pressure causes stalls.

## plain_note  recall 1.0  blocking=False  0.0s / 0 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Dentist Thu 3pm, bring insurance card. Ask about the night guard. Pick up Mira's inhaler refill before 6.

## promo_filler_reel  recall 0.67  blocking=True  6.6s / 1 calls
missing(critical)=['500 ml', '45 minutes'] forbidden=[] invented=[] commentary=0

My 5am routine

## Steps

1. The routine starts by waking up at five.
2. No phone is used for the first hour after waking.
3. Five hundred ml of water is drunk.
4. Ten minutes of mobility is done.
5. At six, writing is done for forty-five minutes before anything else.

## Claims

- The research on a cold shower is weak, and it is optional.

## incomplete_list  recall 1.0  blocking=False  4.6s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Ten habits of great engineers

- One habit of great engineers is that they write design documents before writing code.
- Two habits of great engineers is that they read the code of the tools they use.
- Three habits of great engineers is that they delete code happily.
- Four habits of great engineers is that they ask what problem is being solved before asking how.

**Limits:** The remaining six habits of great engineers are not provided.

## ocr_config_screenshot  recall 1.0  blocking=False  9.6s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

**Why saved:** Settings to copy for the nginx rate limit

Nginx rate limit settings

## Steps

1. Define a rate limiting zone using the command limit_req_zone $binary_remote_addr zone=api:10m rate=5r/s;
2. Within the server block, configure the location /api/ to use rate limiting.
3. Apply the rate limit using the command limit_req zone=api burst=10 nodelay;
4. Set the status code returned when the rate limit is exceeded using limit_req_status 429;

## Facts

- The rate limiting configuration is placed within the http block in nginx.conf.

## Also in the source

- The zone size is 10m, which is approximately 160k IPs.
- Reload nginx using the command sudo nginx -s reload.

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

## paper_results  recall 1.0  blocking=False  10.9s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

WindowSparse abstract and limitations

## Facts

- On the LongDocQA benchmark, WindowSparse reaches 71.4 F1.
- Full attention reached 68.9 F1 on the LongDocQA benchmark.
- WindowSparse uses 3.1x less memory at 16k tokens compared to full attention.
- Memory at 16k tokens was 38.2 GB for full attention.
- Memory at 16k tokens was 12.3 GB for WindowSparse.
- Training utilized 64 A100 GPUs for 9 days.
- WindowSparse underperforms on tasks requiring long-range exact copy.
- WindowSparse drops to 41.0 F1 on the SyntheticCopy task.
- Full attention reached 88.5 F1 on the SyntheticCopy task.

## Claims

- The improvement over full attention is within one standard deviation on three of the five tasks.

## Definitions

- WindowSparse is a sparse attention pattern that combines local windows of 512 tokens with 8 global tokens per layer.

## Caveats

- The evaluation did not proceed beyond 32k tokens.

## correction_in_talk  recall 1.0  blocking=False  8.0s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Database Sharding Experience

## Steps

1. The strategy was switched to sharding by document id hash.

## Facts

- The initial search cluster had 8 nodes.
- The initial sharding strategy was sharding by customer.
- The sharding by customer strategy handled 2,000 queries per second.
- One huge customer caused one shard to become hot.
- P99 latency hit 900 ms with sharding by customer.
- After the switch, p99 dropped to 120 ms.
- The cluster moved to 12 nodes after the switch.

## Claims

- Do not shard on a key whose distribution is not controlled.
