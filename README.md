# NorthStar: cloud build project

This project builds and tests NorthStar's Docker images on GitHub's hosted Linux
runner. Docker Desktop and a working local WSL installation are not prerequisites.

The source is adapted from the supplied NorthStar website. Its catalogue, account,
cart, checkout, support and administration features remain available. The cloud
variant uses PostgreSQL for shared data and Gunicorn for HTTP application workers.
Nginx is a separate web container. Cloud containers require PostgreSQL and do not
silently fall back to a container-local SQLite database.

## Current milestone and honest deployment status

The initial GitHub push runs the Python regression suite, builds both images, and
starts an isolated three-tier test deployment on the GitHub runner. It starts two
application containers, exercises the HTTP API and confirms that both application
containers can be reached through Nginx. Test data is disposable and is removed
with the CI database at the end of the run.

That temporary CI deployment is not the public AWS application. AWS publishing
and deployment steps remain skipped until the AWS account, IAM trust, repositories
and application service are configured. The workflow summary states this explicitly.
The first green build must not be described as a successful AWS deployment.

Verified on 31 October 2026: [workflow run 41218715730](https://github.com/furqan-20/northstar-cloud/actions/runs/41218715730)
passed the original twelve regression checks and twelve Docker/PostgreSQL HTTP
checks, authenticated through OIDC, and published both images to ECR. Its AWS
deployment step was skipped. The `northstar-network` VPC stack was subsequently
created successfully. The remaining hosting services have **not** yet been
deployed or tested at the time this setup update was prepared.

## First step: put this source in GitHub

1. Extract the ZIP on Windows. Open the `NorthStar_Cloud` folder.
2. Create an empty GitHub repository named `northstar-cloud`. Public visibility
   permits the assessor to view the source; a private repository requires appropriate
   access and a review of GitHub Actions usage allowances.
3. Do not initialize the empty remote with a README, license or .gitignore; these
   files are already in this project.
4. In PowerShell, change into this extracted folder. Replace the remote URL below
   with the actual URL of your empty repository:

   ```powershell
   git init -b main
   git add .
   git commit -m "Prepare NorthStar for cloud builds"
   git remote add origin https://github.com/YOUR-USERNAME/northstar-cloud.git
   git push -u origin main
   ```

   If Git requests a commit identity, set `git config user.name "YOUR NAME"` and
   `git config user.email "YOUR GITHUB NOREPLY EMAIL"` in this repository, then
   repeat the commit. A GitHub noreply address avoids publishing a personal email
   address in commit history. Git for Windows may open a browser for authentication.
5. Open the repository's Actions tab and select **NorthStar cloud build and deployment**.
   Confirm that the regression, Docker build and running-application checks pass.
   No report screenshot is requested at this setup stage.

The `.github` directory must be included. Using the Git commands above includes it
automatically, even if Explorer hides it. Never upload `.venv`, real `.env` files,
local databases or real credentials.

## Build and release flow

`Push to main -> regression tests -> two Docker image builds -> temporary PostgreSQL
+ two app containers + Nginx -> HTTP checks -> ECR push -> ECS rollout -> live checks`.

Pull requests run the build and tests but cannot publish or deploy. Deployment
credentials use OIDC rather than stored AWS access keys. Configure the role's trust
for the exact repository and main branch. GitHub's current immutable subject format
includes owner and repository IDs for new repositories; use the subject format of
the actual repository instead of copying an older example blindly.

ECR tags include the source commit, workflow run ID and attempt. The pipeline pushes
the images already tested on the runner. It updates containers named `app` and `web`
in an existing ECS service, waits for service stability, verifies the selected task
definition is still active, and checks the deployed commit via `/healthz`. Failed
verification requests a return to the previous task definition and fails the run;
the restoration must itself be checked before claiming recovery completed.

## AWS configuration

The [AWS setup guide](infra/README.md) describes the CloudShell provisioning script,
reviewable CloudFormation template, cost plan, security boundaries and known NFR
limitations. It uses the existing VPC, two ECS Fargate tasks, an ALB, private RDS
PostgreSQL, one NAT gateway, Secrets Manager, CloudWatch Logs and CloudFront HTTPS.
Web and app containers share each task, as permitted by the assignment.

The initial push creates no AWS resources. `infra/provision.py --plan` performs
read-only AWS checks. Explicitly running `--deploy` provisions billable hosting,
initializes the database with a separate owner role, enables the service, checks
the live URL and adds the GitHub deployment policy. Review the estimated usage
through the evaluation on **20 November 2026** before running it.

After that setup, configure repository **Actions variables**, not plaintext source
files, with the actual values:

| Variable | Meaning |
|---|---|
| `AWS_ROLE_ARN` | Role trusted for this repository's main-branch OIDC token. |
| `AWS_REGION` | Confirmed deployment region; workflow default is `eu-north-1`. |
| `ECR_APP_REPOSITORY` | Application repository name; default `northstar-app`. |
| `ECR_WEB_REPOSITORY` | Web repository name; default `northstar-web`. |
| `ECS_CLUSTER` | Existing ECS cluster name or ARN. |
| `ECS_SERVICE` | Existing service name. |
| `APPLICATION_URL` | Actual public application URL, including its scheme. |

The deployment role needs permission to push only to the two ECR repositories,
read task definitions, register the required new task revisions, update the specific
ECS service, and pass only the approved ECS task/execution roles. It does not need
AdministratorAccess. The existing main-branch OIDC trust is preserved by the setup.

## Application configuration

| Setting | Purpose |
|---|---|
| `NORTHSTAR_DB_HOST`, `NORTHSTAR_DB_PORT`, `NORTHSTAR_DB_NAME` | RDS endpoint, port and database. |
| `NORTHSTAR_DB_USER`, `NORTHSTAR_DB_PASSWORD` | Inject through AWS Secrets Manager references in the task definition. |
| `NORTHSTAR_DB_SSLMODE` | Default `verify-full`; CI-only Compose uses `disable` on its isolated network. |
| `NORTHSTAR_DB_SSLROOTCERT` | Default `/etc/ssl/certs/rds/global-bundle.pem`, downloaded from AWS during image build. |
| `NORTHSTAR_AUTO_INIT` | Default `1`; initialize schema/catalogue before starting workers. Set `0` after a separate migration step when using an application database role without DDL permission. |
| `NORTHSTAR_SEED_DEMO` | Cloud default `0`; published local demonstration passwords are not seeded. |
| `NORTHSTAR_ADMIN_EMAIL`, `NORTHSTAR_ADMIN_PASSWORD` | Optional first administrator. Inject a unique password of at least 16 characters from Secrets Manager; never commit it. Existing administrator credentials are not reset by initialization. |
| `NORTHSTAR_SECURE_COOKIE` | Set `1` when the final public endpoint uses HTTPS. Configure TLS before using real accounts. |
| `NORTHSTAR_TRUST_PROXY` | Set `1` only with the application's ingress restricted to the trusted web tier. |
| `APP_UPSTREAM` | Nginx target; `app:8000` in Compose, normally `127.0.0.1:8000` when the two containers share a Fargate task. |
| `TRUSTED_PROXY_CIDR` | Nginx trusts forwarded client IPs only from this CIDR. Set it to the actual ALB network boundary; restrict ingress with security groups too. |
| `CLIENT_IP_HEADER` | Nginx real-IP header; default `X-Forwarded-For` for Compose, `CloudFront-Viewer-Address` behind the restricted CloudFront/ALB origin. |

`DATABASE_URL` is an alternative PostgreSQL connection string for development and
testing. Keep it outside the repository. No existing SQLite customer data is imported
automatically; RDS starts with a fresh catalogue and accounts created for the demo.

Schema initialization is idempotent and uses a PostgreSQL advisory lock so two
starting containers cannot seed simultaneously. Critical cart/order transactions
use another transaction advisory lock to preserve the original application's
serialized write behavior. This favors correctness for the course workload; it
limits write throughput and is a limitation to discuss in the NFR section.

## Tests and evidence

- `tests/test_cloud_application.py`: ten automated application regression tests, including
  authentication, address CRUD and ownership, CSRF, search, order idempotency and
  stock restoration, cookie flags, administrator access and seed behavior.
- `tests/test_deployment_guard.py`: two tests for preserving secret references and
  reporting an ECS rollback as a failed release. These use mocked AWS responses;
  they are not evidence of an actual AWS deployment or recovery.
- `tests/test_infrastructure_guards.py`: four tests that prevent unmatched image
  pairs, resolve initial image digests to the tested source revision, and prevent
  modifications to an IAM role belonging to another project. The current local
  regression suite totals sixteen tests; the next GitHub run must verify them too.
- `scripts/smoke.py --full`: twelve HTTP checks against the temporary PostgreSQL,
  Gunicorn and Nginx deployment, including two application containers.
- `cloud-build-results.json`: actual CI check results, saved as a workflow artifact.
  This is generated when the workflow runs, not a prefilled success claim.
- The final live check is read-only: readiness/revision, website/assets and search.

Full Docker and PostgreSQL integration results must come from an actual successful
GitHub Actions run. Source preparation and local Python regression results alone
are not proof of container build or AWS deployment success.

Only report evidence is to be captured. The final eight categories remain VPC,
compute/container tasks, security groups, load balancer, database, image build and
registry, full CI/CD deployment, and the running public website. Reuse the final CI
build log for build evidence. No screenshots are needed for installing tools,
creating the repository, initial test runs or Windows troubleshooting.

## Optional local Compose usage

This is not required on the student's Windows laptop. On a machine with Docker,
copy `.env.example` to `.env`, replace the placeholder password, then run
`docker compose up --build -d --wait`. The app is at `http://127.0.0.1:8080`.
The database has no host-published port. Its named volume persists across normal
restarts. Do not use `docker compose down --volumes` against data you want to keep.
The workflow's volume removal applies only to its disposable GitHub runner database.

## Source register

- `Dockerfile`: application image.
- `docker/web.Dockerfile`: web image.
- `docker/default.conf.template`: web proxy and security headers.
- `docker-compose.yml`: reproducible three-tier CI test environment.
- `.github/workflows/deploy.yml`: build, test, registry and deployment workflow.
- `wsgi.py`, `gunicorn.conf.py`, `database.py`: cloud adaptation.
- `scripts/initialize.py`, `scripts/smoke.py`, `scripts/deploy_ecs.py`: initialization,
  verification and deployment helpers.
- `README_Original.md`: original local website documentation.

Kubernetes is not selected for this approach, so Kubernetes manifests are not applicable.
The 4-6 page report, final architecture diagram, AWS provisioning files and deployment
evidence will be completed against the resources actually deployed.

## References

- https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- https://docs.docker.com/build/ci/github-actions/
- https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws
- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html
