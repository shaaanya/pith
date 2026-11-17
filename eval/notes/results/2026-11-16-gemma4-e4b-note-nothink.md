# note-nothink (gemma4:e4b)

```json
{
 "variant": "note-nothink",
 "model": "gemma4:e4b",
 "cases": 14,
 "mean_recall": 0.92,
 "blocking": 4,
 "commentary_total": 8,
 "invented_number_cases": 0,
 "mean_words": 131,
 "total_calls": 12,
 "total_seconds": 694.3
}
```

## twitch_reel  recall 1.0  blocking=False  160.3s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=1

This source is a 30-day preparation plan for an entry-level Payments Software Engineer role at Twitch.

## Steps

1. Figure out the tech stack by looking at older Twitch job postings and engineering blog articles.
2. Learn the payments basics, which are idempotency and database transactions.
3. Do the Tour of Go.
4. Read Marc Brooker's writing about DynamoDB and Aurora DSQL.
5. Practice system design on Devmaxx every morning, focusing on the database questions.
6. Build a fishing tournament manager using Lambda, DynamoDB, SQS, and Step Functions.

## Facts

- Twitch posted an entry-level Payments Software Engineer role with a salary range of $127K-$185K.
- The tech stack includes Go, DynamoDB, Lambda, SQS, and Step Functions.
- Chapter 7 of Designing Data-Intensive Applications should be read for payments basics.

**Limits:** The full guide mentioned in the source is not provided.

## postgres_noisy_transcript  recall 1.0  blocking=False  77.6s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

This source is a list of Postgres performance fixes shared by an unnamed speaker.

- Use CREATE INDEX CONCURRENTLY to prevent blocking tables during writes.
- Always run EXPLAIN (ANALYZE, BUFFERS) before and after making a change.
- Replace OFFSET pagination with keyset pagination.
- Keyset pagination uses the structure WHERE id > $last_id ORDER BY id LIMIT 50.

**Limits:** No specific names or dates were provided for the fixes.

## podcast_brief_mention_intent  recall 1.0  blocking=False  123.2s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=1

**Why saved:** Saved for the Claude Code skill mentioned in the middle

This source is Episode 41 discussing agent workflows, code review habits, and burnout among two speakers.

## Relevant to why you saved this

- One way to improve debugging involves the Claude Code skill called systematic-debugging.
- Systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.
- They discussed how on call rotations should change when agents ship code at night.

## Also in the source

## Facts

- The discussion is about shipping faster with coding agents.
- Dana thinks the biggest win from coding agents is fewer context switches.
- Marcus blocks mornings for deep work and avoids meetings before noon.
- They agreed to cap work in progress at three tasks.

## Claims

- Marcus disagrees with Dana, claiming review time just moves to a different place.
- Dana maintains that small pull requests still matter because reviewers still read linearly.
- Dana asserts that burnout is the real risk with agents because the pace never drops.

## Resources

- Four Thousand Weeks by Oliver Burkeman is recommended by Marcus for thinking about limits.

**Limits:** No specific numbers or dates beyond the mention of Episode 41 were provided.

## podcast_brief_mention_no_intent  recall 1.0  blocking=False  129.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=1

This is an episode discussion about shipping faster with coding agents, featuring Dana and Marcus.

## Steps

1. Systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.

## Facts

- The discussion is about shipping faster with coding agents.
- Dana thinks the biggest win is fewer context switches.
- Marcus disagrees, stating that review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- There is a Claude Code skill called systematic-debugging.
- Marcus blocks mornings for deep work and does no meetings before noon.
- Dana says burnout is the real risk with agents because the pace never drops.
- Dana and Marcus agree to cap work in progress at three tasks.
- They discuss how on call rotations should change when agents ship code at night.

## Resources

- Four Thousand Weeks by Oliver Burkeman

**Limits:** The source does not provide a quantity of specific workflows discussed.

## docker_tutorial  recall 0.55  blocking=True  65.0s / 1 calls
missing(critical)=['docker build -t flaskapp .', '-p 80:8000', '--env-file .env'] forbidden=[] invented=[] commentary=1

This source provides instructions on deploying a Flask app on a VPS with Docker.

1. First create a Dockerfile starting from python 3.12 slim.
2. Copy requirements.txt and run pip install no cache dir.
3. Then copy the app and set the command to gunicorn bound to 0.0.0.0 port 8000 with app colon app.
4. Build it with docker build dash t Flask app dot.
5. Run it with docker run dash d dash p 80 colon 8000 dash dash env file dot env dash dash restart unless stopped Flask app.
6. Your dot env needs DATABASE_URL and SECRET_KEY.
7. Never commit that file and add it to dot gitignore.
8. If the container exits check docker logs Flask app.
9. For https put caddy in front it gets the certificate automatically.
10. The caddyfile is just your domain and reverse underscore proxy localhost colon 8000.

**Limits:** The number of instructions provided is 10, but the instructions are provided.

## opinion_essay  recall 1.0  blocking=False  23.9s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

## Facts

- At one company, commit counts per developer rose 40% within a quarter after they were added to a dashboard.
- Shipped features per quarter fell from 11 to 8 at that company.
- A one line fix to a payment bug can matter more than a month of churn.
- The median waiting time between review and deploy was 3 days.
- DORA metrics are deployment frequency, lead time for changes, change failure rate and time to restore service.

## Claims

- Counting commits measuring developer productivity is a mistake because of Goodhart's law, which states that once a measure becomes a target, it stops being a good measure.
- Developers at that company split work into tiny commits and avoided hard refactors that produce a single large change.
- The first argument is that commits measure activity, not value.
- The second argument is that the metric punishes collaboration because pairing and review produce no commits for the reviewer.
- The third argument is that commit counting hides the real constraint, which in the cases described was waiting time between review and deploy.
- Critics reply that some quantitative signal is needed for management.
- The author concedes this and suggests DORA metrics instead.
- The author notes these metrics should be tracked per team, never per individual, and still carry the risk of gaming.

## news_numbers  recall 1.0  blocking=False  18.0s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=1

This source is a news report regarding a ferry service suspension by Harbour Ferries.

## Facts

- Harbour Ferries suspended all sailings on the Kestrel route on Tuesday 14 October.
- The suspension happened after an inspection found cracks in the hull of the MV Linnet.
- The company confirmed 212 passengers were on board when the cracks were reported on 9 October.
- Nobody was hurt when the cracks were reported.
- The MV Linnet was built in 1998.
- The Linnet carries up to 340 passengers.
- Transport minister Priya Anand stated the suspension would last at least 3 weeks.
- Transport minister Priya Anand said the ferry operator would receive no compensation for lost fares.
- Replacement buses will run every 20 minutes from Wednesday.
- The replacement bus fare is 4.50 pounds per trip.
- The replacement bus fare is the same as the ferry fare.

## Claims

- Union representative Tom Reyes alleged that two earlier inspection reports in 2023 had flagged corrosion and were not acted on.
- Harbour Ferries denied the allegation and said the 2023 reports found only cosmetic wear.

## Caveats

- The claim regarding the 2023 reports has not been verified.

**Limits:** The text mentions 2023 reports but does not provide the full date for the two reports.

## web_table_article  recall 1.0  blocking=False  17.4s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

## Steps

1. Start with a managed queue unless replay is needed.
2. Pick Kafka only if consumers must re-read history or if 100,000 messages per second or more are needed.
3. Pick SQS FIFO when order matters per customer.

## Facts

- Amazon SQS Standard has best effort ordering, no replay, a maximum message size of 256 KB, and no ops cost.
- Amazon SQS FIFO has strict per group ordering, no replay, a maximum message size of 256 KB, and no ops cost.
- Apache Kafka has strict per partition ordering, replay capability, a default maximum message size of 1 MB, and high ops cost.
- RabbitMQ has per queue ordering, no replay, a maximum message size of 128 MB, and medium ops cost.

## Claims

- The decision for most teams comes down to ordering guarantees and operational cost.

## Caveats

- Avoid RabbitMQ lazy queues for payloads near the 128 MB limit because memory pressure causes stalls.

**Limits:** No additional specific data points beyond the table and concluding sentences were provided.

## plain_note  recall 1.0  blocking=False  0.0s / 0 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Dentist Thu 3pm, bring insurance card. Ask about the night guard. Pick up Mira's inhaler refill before 6.

## promo_filler_reel  recall 0.83  blocking=True  19.2s / 1 calls
missing(critical)=['no phone'] forbidden=[] invented=[] commentary=2

This source describes a 5 am routine spoken by the creator.

- The creator drinks 500 ml of water.
- The creator does ten minutes of mobility after drinking water.
- The creator writes for 45 minutes at six before anything else.
- A cold shower is optional because the research on it is weak.

**Limits:** The source does not provide the full details of the course mentioned.

## incomplete_list  recall 0.5  blocking=True  13.4s / 1 calls
missing(critical)=['read the code', 'what problem'] forbidden=[] invented=[] commentary=0

This source lists ten habits of great engineers, spoken by the creator.

- There are ten habits of great engineers.
- One habit is writing design docs before writing code.
- Two habits is reading the code of the tools that are used.
- Three habits is deleting code happily.

**Limits:** The rest of the ten habits are not provided.

## ocr_config_screenshot  recall 1.0  blocking=False  0.0s / 0 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

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

## paper_results  recall 1.0  blocking=False  28.5s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=1

This abstract and table describe the WindowSparse attention pattern and its performance.

## Facts

- On the LongDocQA benchmark WindowSparse reaches 71.4 F1.
- Full attention reached 68.9 F1 on the LongDocQA benchmark.
- WindowSparse used 3.1x less memory at 16k tokens.
- Table 2 shows that full attention used 38.2 GB of memory at 16k tokens.
- Table 2 shows that WindowSparse used 12.3 GB of memory at 16k tokens.
- Training used 64 A100 GPUs for 9 days.
- WindowSparse underperforms on tasks requiring long-range exact copy.
- WindowSparse dropped to 41.0 F1 on the SyntheticCopy task.
- Full attention achieved 88.5 F1 on the SyntheticCopy task.
- The evaluation did not extend beyond 32k tokens.

## Claims

- WindowSparse proposes a sparse attention pattern combining local windows of 512 tokens with 8 global tokens per layer.
- The improvement over full attention was noted within one standard deviation on three of the five tasks.

**Limits:** The text does not provide the specific tasks mentioned when stating an improvement was noted on three out of five tasks.

## correction_in_talk  recall 1.0  blocking=True  18.0s / 1 calls
missing(critical)=[] forbidden=['had 6 nodes'] invented=[] commentary=0

This is an account of a search cluster scaling experience shared by the speaker.

## Steps

1. The team switched to sharding by document id hash.

## Facts

- The search cluster initially had 6 nodes.
- One huge customer caused one shard to become hot.
- P99 latency hit 900 ms.
- The original cluster had 8 nodes not 6.
- After the switch, p99 dropped to 120 ms.
- The team moved to 12 nodes.

## Claims

- Sharding by customer was initially thought to be the answer because it handled 2,000 queries per second.
- Do not shard on a key whose distribution you do not control.
