# Repository presentation and hosting review

Reviewed 30 October 2026. The sample revisits the same Meta, Anthropic and Google
winners used for the workbench research. READMEs and root directories were read
at the commits below; no winner code was installed or executed.

These snapshots can contain work after the contests. They establish published
presentation choices, not the exact submitted builds or a formula for winning.

## Source sample

| Project | Award verification | README snapshot | Root structure |
| --- | --- | --- | --- |
| OrgLens | [Meta announcement](https://www.linkedin.com/posts/meta-for-developers_were-excited-to-announce-the-winners-of-activity-7325596881483354112-Kvt5) | [c07af10](https://github.com/TheCl3m/llama-hack/blob/c07af10f61a50e2e12b8600b3492504f952eb8ab/README.md) | backend, frontend, images |
| CrossBeam | [Anthropic Opus 4.6 winners](https://claude.com/resources/articles/meet-the-winners-of-our-built-with-opus-4-6-claude-code-hackathon) | [cc5591e](https://github.com/mikeOnBreeze/cc-crossbeam/blob/cc5591e7e824ba5cafa9b8c6507258b996aac011/README.md) | frontend, server, docs, scripts, test-assets |
| Elisa | Same Opus 4.6 announcement | [10f7880](https://github.com/zoidbergclawd/elisa/blob/10f7880a603af1e61f2737cffaeffbf6b159b620/README.md) | frontend, backend, electron, docs, scripts |
| Wrench Board | [Anthropic Opus 4.7 winners](https://claude.com/resources/articles/meet-the-winners-of-built-with-opus-4-7-claude-code-hackathon) | [cded162](https://github.com/Junkz3/wrench-board/blob/cded162b69e1c7f8b8604cf0081f7600188ba522/README.md) | web, api, rust, tests, fixtures, benchmark, docs |
| Medkit | Same Opus 4.7 announcement | [3f637a8](https://github.com/bedriyan/medkit-app/blob/3f637a8afd76b81e520bfeae3af9fbf32b601594/README.md) | src, backend, agent, public, docs, scripts |
| Gaze Link | [Google Android award account](https://android-developers.googleblog.com/2024/11/gaze-link-wins-best-android-app-gemini-api-developer-competition.html) and the previously verified creator/repository chain | [e0ccea7](https://github.com/Jonassunhk/Gaze-Link/blob/e0ccea7386848df6f5d28fb7a8b5b6d35015e72a/README.md) | Android source under Develop |

Wrench Board and Medkit extend the earlier Opus 4.7 comparison; the originally
selected Anthropic event remains Opus 4.6. Gaze Link is Android evidence, not a
React website. No verified Trippy or ViddyScribe source was available in this
review, so neither is represented as source-audited.

## Patterns worth adopting

| Observed practice | Evidence | Remnant X application |
| --- | --- | --- |
| Explain the domain task before the stack | OrgLens, CrossBeam, Medkit and Gaze Link lead with a concrete user/problem | Lead with photographing offcuts and planning new parts |
| Show inspectable proof early | OrgLens embeds a video; Elisa a UI GIF; Wrench Board a screenshot, video and viewer link | Use a screenshot from our actual recorded example and a clear local walkthrough |
| Give the right entry point for the product | Elisa offers installers; Gaze Link links a manual; other repos give separate client/server commands | Distinguish key-free example startup from live API setup |
| Explain why responsibilities are split | CrossBeam explains its long-job hosting; Medkit separates frontend, HTTP and voice roles | Show exactly where SAM, order interpretation and deterministic geometry operate |
| Keep supporting evidence outside the introduction | Several repos link docs, fixtures, tests and scripts | Keep the root README concise; link the engineering reference and measured validation |
| State scope explicitly | CrossBeam labels an unbuilt flow as roadmap; Medkit identifies synthetic cases | Retain cardboard errors, supported DXFs/controllers and the absence of machine qualification |

The root layouts vary considerably. Directory names, a particular framework,
source length and a custom domain are not common requirements across the sample.
Some repositories also publish agent instructions and development journals.
Our public documentation records decisions and evidence; private chat transcripts
and handoff notes remain excluded.

## Did winners use purchased domains?

| Project | Published access pattern | What was verified |
| --- | --- | --- |
| OrgLens | README documents local Django/Vite startup; repository homepage is empty | No hosted address is advertised in that snapshot; this does not prove none existed |
| CrossBeam | Repository homepage lists www.crossbeam-permits.com | Custom address listed; the web fetch timed out, so current app availability was not verified |
| Elisa | GitHub Releases installers and local source startup | A desktop distribution path, with no repository homepage listed |
| Wrench Board | app.wrenchboard.cloud and a separate boardview viewer | App URL redirected to signup; README advertises a separate free viewer |
| Medkit | [medkit-app.vercel.app](https://medkit-app.vercel.app/) | The provider-domain landing page loaded and offered demo/live links |
| Gaze Link | Android source, Google Docs manual and YouTube channel | The README does not advertise a browser app or custom domain |

Those are current published addresses, not proof of domain ownership or the URLs
used during judging. In particular, a landing page loading is not a full test of
the application's backend.

[Vercel's documentation](https://vercel.com/docs/domains/working-with-domains)
confirms that deployments receive a `.vercel.app` address.
[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
supports a default `github.io` project address and static HTML/CSS/JavaScript.
A custom domain is an optional distribution choice in those services.

For Remnant X, buying a domain is unnecessary for local filming or a
provider-hosted static example. A public live workflow would also need a hosted
FastAPI process, persistent inventory, server-side credentials and appropriate
access controls. A frontend hostname alone does not supply those.

The current frontend uses root-relative assets. A root-hosted provider address
fits that layout; GitHub Pages project-subpath hosting would need base-path
configuration. The separate architecture explorer is static HTML, not a FastAPI host.

## README guidance and event requirements

No Meta-authored “best README” specification was verified in the reviewed
[official event page](https://dev.meta.ai/events/global-hackathon) or
[Cerebral Valley listing](https://cerebralvalley.ai/e/meta-ai-developer-hackathon),
or the targeted official-site searches. This is not proof that private participant
guidance does not exist. Full submission-form requirements, a compulsory hosted
demo and a required custom domain remain unverified here.

The documented baseline used instead is
[GitHub's own README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes):
explain usefulness, capabilities, getting started, help and maintainership.
Winner-source observations inform our presentation; they are not attributed to Meta.

## Resulting changes

The project README now prioritizes the problem, visible output, key-free trial,
live workflow, model responsibilities, current evidence and repository map.
Detailed API/controller contracts remain in a separate engineering reference.
The screenshots use synthetic example data; private physical photos remain private.
The small UI refinements improve photo-overlay contrast, provenance labels and
the example's independence from backend availability. The existing geometry,
verification and inventory architecture is retained.
