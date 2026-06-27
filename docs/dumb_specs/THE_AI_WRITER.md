Okay so this will serve as the ultimate source of thruth, because usually the superpowers specs are way too detailed and sometimes they do not capture the core idea I want to make.

Problem Definition:
So this program will be writing PAPER.md based on the skills design-experiment and research-question.
Basicly every question (in the question) has its experiments. Each experiment can look very differently.
Each experiment should have some artefacts that are made from the runs that were executed, experiments READMEs sometimes (not always) includes takeaway and description of the expriment.
Now the goal is to write a paper that answer the questions answers based on the experiment data.
Who is the paper for? it is for a client that the questions were answered for.. For example the datera project /home/tomja/Documents/work/datera/questions has experiments and questions related to OCR optimization, because the client is interested in running more effiecient models. It answers various things, right.

What I imagine this product shall do?
It goes through the experiments and questions and writes the paper.

How does it do it?
What I want to do is to itiliza AI agents (we are working with codex and claude clis). Basicly the same way when you start or resume the project with this cli agent, you tell it to get some context... The same way it should work with experiments and the questions framework.

1. We start from inner experiments. For each experiment we try do such "get some context". Basicly I want to utilize what codex already does well, so in each experiments folder I tell it to recieve context, then let it run its pipeline.
Then it produces experiments README.md (if it already does not exist).
Then I want it run review that will fact check, if numbers and tables match the experiments, so it will just go through the README again and make sure the results are not halluicnated.
This will be done in paralel across all of the experiments using subagents.
2. Then there is writing part, now here we will try to the paper it self, now, sometimes we have a lot of experiments and not of all of them are relevant, because sometimes some experiments are only the more recent version of a previous experiment. So there should be some kind of ranking systems on what to include.
3. After the ranking is done, we look into quesitons and try to answer the research questions that are in based on the experiments that we have availible.
4. now that that is done we begin a writing. Writing should be as short as possible and utilize the logic, where we are not explaining the details and only the takeaways, the details are already either in the questions readmes or in the experiments readmes...
5. Style check, even tho we already tried to be short with the description, the tone might not be enough.. The tone should not sound too scientific, but it should still sound professional. Simplicity is that what we are going for.


How will I use it?
1. I will ideally call it from inside the codex cli (so with skill)
2. I will want to select which experiments to run it on, because sometimes I already know some of the experiments are shit and hsould not be included
3. I want it to be very verbous somehow about what it is currently doing, so if it would communicate progress somehow, that would be lovely, ideally some kind of python watcher with nice uv rich UI that would just dispay how many subagents are deployed and what they are currently doing
4. So then after the analysis of the experiments are done I would love to start writing, I do not want the AI to one shot the writing tho, so I would like to start with its recommendation for the quesion redefinitions, because sometimes experiments drift from the questions definition and just share the same folder (that is alright).. This is because I do not want the ai to try to match experiments on a research question that does not match the experiment just because it is in the same folder..
5. then we start actual writing, section by section.. I want this to be iterative somehow, I want the codex cli (or claude whatever) to ask me my opinion about if it should be in or not
6. after everything is done, I should obviously be able to change the final PAPER.md, but I guess that would still be possible...

What technologies I want it to use?
So basicly mainly skills, maybe MCP servers (if you feel like any could be useful), maybe some simple python package for orchestration but this is a big maybe... If you look into folder decisions and other specs that were written prior to this file, there already was an attempt, but it got way too complicated and it did not work... So do not overengineer it.
