## Minimum Viable Coding Agents 

A recursive self-improving agent needs three things: a model, a shell, and a safe way to update itself. Everything else can be bootstrapped later. I created a quick 32-line python script that evolves on its own.

After one iteration it grew into a tiny coding agent and named itself Claudette. Claudette can build many things, including increasingly better versions of itself. It has very few bells and whistles – just some basic helpers for history management and recovery.

Claudette behaves like most coding agents, it can plan, build, test, and iterate. It will run for hours if you let it (watch your tokens!). I let it run for a while to build a few apps. So far: an 8-bit emulator, several games, and the beginnings of something similar to OpenClaw. It also gave itself many upgrades along the way, like support for durable tasks, model selection, and worktrees.

<p align="center">
  <img src="game-image-small.gif" alt="Game demo">
</p>

After a few more iterations Claudette created a platformer game, learned to play it, and then iterated on its own code until it could finish the game in record time.

> Try it out for yourself!
>
> 1. Clone the github repo to get the files
> 2. Set: OPENAI_API_KEY in your environment
> 3. Run the minimum viable agent: python3 mva.py
> 4. Run the minimum viable coding agent: python3 mvca.py
>
> If you're going to run these agents, I'd suggest using a sandbox. They may create files, folders, and run shell commands. They should ask you for permission, but have been known to misbehave.


Learn more at [bertolami.com](https://www.bertolami.com/blog/minimum-viable-coding-agents).