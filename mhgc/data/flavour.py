"""Dave's report flavour text, ported verbatim from the C (gcleader.c, gcrandom.c, gcrun.c,
gccombat.c) so the structured events keep the game's voice.  Typos fixed only where obvious."""

LEADER_GOOD_EVENT = (
    "squanders the opportunity represented by the event",
    "provides adequate leadership during the opportunity",
    "takes full advantage of the situation",
)
LEADER_BAD_EVENT = (
    "exacerbates the disaster with inept handling of the crisis",
    "provides adequate leadership during the crisis",
    "performs outstandingly during the course of the situation",
)

COMMENT_SOURCE = (
    "The hyperspace junction journal ",
    "The GOV:FINANCE council ",
    "Your good friend General Bratweister ",
    "Your old SPACE:FORCE buddy Admiral Mangobler ",
    "The local council of businesses ",
    "The subsecretary of the googaplexbit information megahighway ",
)
COMMENT_VERB = ("writes ", "sends via Hmail channels ", "drops a line ",
                "uses the vidphone to chat with you ")
COMMENT_GRADE = ("unbelievably moronic ", "stupid ", "poor ", "marginal ", "adequate ",
                 "pretty good ", "fine ", "outstanding ", "phenomenal ",
                 "absolutely unbelievable ")
COMMENT_TOPIC = {
    "mgmt": ("on jump starting the recovery from the latest global recession.",
             "balancing the GOV:FINANCE budget.",
             "improving business forecasts with tax breaks.",
             "selecting the new GOV:FINANCE council for Hmail money transfers."),
    "eng": ("on the plan for the hyperspacial link with moon Gamma 12.",
            "certifying the new neutrino detection grid for trans-system scanning.",
            "selecting Dr. Gobran's cold fusion experiment for funding.",
            "appointing the new head of the meta-physical hyperspace council."),
    "intel": ("on his commencement speech at Virtual U.",
              "on solving Rubic's hypercube on world-wide tri-V.",
              "reviewing Dr. Magascon's quantum meta space theorem",
              "with the latest GOV:STANDARDS IQ testing."),
    "social": ("working with the association of homeless three-eyed introverts.",
               "on handling the rumors of an affair with Megonon, the Tri-V star.",
               "at the dinner hosted by the restless young empirians association.",
               "courting the media on the difficult issue of sewage disposal."),
    "combat": ("on suppressing the hypernet bandit rebellion.",
               "in the latest MILSIM competition, 'Nuke The Bastards'.",
               "with the review of OPORD 67, anti-invasion tactics.",
               "on his decision to fund the mark six hyper-strat megadeath ray."),
}

DESC_CAREER = (
    "worked his way up through FORCE:SPACE with a combination of political skill, brilliance "
    "in tactics and strategy, and luck.  ",
    "moved through the ranks of FORCE:SPACE R&D centers, demonstrating an unusually strong "
    "grasp of the underlying quantum hyperdynamic megaquantum mathematics theory used in the "
    "development of the latest weapons systems.   Many feel, however, he is not working up to "
    "his actual potential.  ",
    "received a political appointment to FORCE:SEA.  ",
    "worked his way up through FORCE:GROUND with sheer hard work.  ",
    "demonstrated an outstanding grasp of new tactics with newly deployed weapons systems.  He "
    "wangled several promotions out of this in FORCE:GROUND, winning several important "
    "victories.  ",
    "showed a flair of brilliance in strategy and tactics in MilSim competitions and actual "
    "battlefield conditions.  ",
    "made steady progress through the ranks for FORCE:SPACE by demonstrating strong "
    "intellectual capabilities, although their actual performance was somewhat "
    "disappointing.  ",
)
DESC_REPUTATION = (
    "He has a reputation as a extremely capable but iron-fisted leader.  ",
    "The rumor mill classifies them as more politically correct than truly capable, although "
    "this could be attributed to jealousy.  ",
    "Many say he has climbed far, and quickly, but has gone as far as he is likely to go.  ",
    "Despite mediocre performance in many situations, he has been praised again and again for "
    "his outstanding potential.  ",
)
DESC_SKILL = {
    "eng": (
        "A graduate of Megatron Institute of Technology, he studied Hyperspacial Engineering, "
        "graduating second in his class.  ",
        "Graduating from Caltron Technical University, he was considered to have done ground "
        "breaking research in neutrino emissions detection.  ",
        "Forced into the military after quitting Engineering U for personal reasons, he "
        "concentrated on areas that did not require technical expertise.  ",
        "He graduated from World University Branon with a degree in drama, and some suspect his "
        "technical capabilities as a result.  One humorous story that has made the rounds was an "
        "occasion where he spent a half hour attempting to troubleshoot a computer problem, only "
        "to find the unit was unplugged.  "),
    "mgmt": (
        "He reads the Hyperspace Junction Journal regularly and is considered a strong friend "
        "of big business.  ",
        "Considered something of a economic genius, he has regular bylines in the Hyperspace "
        "Junction Journal and has published a few books on the subject of world economic "
        "growth.  ",
        "Considered a friend of the ecology, he has argued many times against economic "
        "expansion at the cost of the environment.  ",
        "Some argue his business sense is such that he is lucky if he gets his checkbook to "
        "balance.  "),
    "combat": (
        "He is considered an excellent tactician; there were several concrete instances where "
        "he won out against overwhelming odds in military conflicts.  ",
        "He has been praised many times for the brilliance of his work on OPORDs for various "
        "military contingencies, and was awarded the Globular Golden Cluster for one "
        "particularly well done MILSPEC.  ",
        "Their detractors argue poor combat skills, pointing at the one battalion under their "
        "command slaughtered by native aborigines on Deltar IV.  The records show, however, "
        "that it was proved conclusively the embarrassing loss was due to malfunctioning "
        "vibra-soles in the FORCE:MARINE boots.  ",
        "Many say he could not fight his way out of a wet paper bag with a Battalion of "
        "Cybertanks.  "),
    "social": (
        "Several impressive Tri-V appearances have boosted his career significantly, allowing "
        "his distinguished, statesmanlike demeanor to be played for maximum effect.  ",
        "A commonly heard statement compares them against Stangit Metagron Jr. one of the most "
        "popular politicians in recent history.  ",
        "Their career has been somewhat damaged by poor presentation technique.  ",
        "An unfortunate comment in the local Hmail vidzine did compare them to Hazzod Maragove, "
        "one of the more self-effacing comedians appearing at the time.  "),
}

# Space combat effectiveness words (gccombat.c:900-915)
EFFECTIVENESS = ((20, "WIMPY"), (40, "poor"), (60, "average"), (80, "excellent"),
                 (101, "DEADLY"))
ADMIRAL_TEXT = ((20, "creates complete chaos for his own ships!"),
                (40, "barely manages to control his own fleet!"),
                (60, "does an adequate job of organizing his fleet"),
                (80, "provides brilliant tactical plans for his units!"),
                (1000, "provides brilliant tactical leadership and raises morale immensely!"))
GOVERNOR_TEXT = ((30, "faints at the sight of blood!"),
                 (50, "attempts to overcome his lack of combat experience!"),
                 (65, "does an adequate job of organizing his defenses"),
                 (80, "provides brilliant leadership in air and space!"),
                 (1000, "motivates his defenses to fight to death and beyond!"))
MISS_TEXT = ((0.25, "easily avoids enemy attack!"), (0.5, "expertly deflects enemy salvo!"),
             (0.75, "manages to avoid enemy attack!"), (10.0, "narrowly misses destruction!"))

SYS_STATUS_TEXT = {
    "no_attack": "No space attacks, system NORMAL",
    "no_attack_ground": "No space or ground attacks, system NORMAL",
    "normal": "Defense greater than 3 time attack, System NORMAL",
    "ua": "System is UNDER ATTACK",
    "int": "Attackers have better than three times defense, system INTERDICTED",
    "int_ground": "Attackers are greater than ground defenses, system INTERDICTED!",
    "no_defense": "attack, but no defense, automatic INTERDICTION",
    "shift_int": "System shifting toward interdiction, currently UNDER ATTACK",
    "shift_norm": "System shifting toward normal, currently UNDER ATTACK",
}


def grade_word(value: int) -> str:
    """COMMENT_GRADE index for a 0..99 rating (gcleader.c:150-160)."""
    for i, lim in enumerate((40, 45, 50, 55, 60, 70, 80, 90, 95)):
        if value <= lim:
            return COMMENT_GRADE[i]
    return COMMENT_GRADE[9]


def wrap60(text: str) -> str:
    """The C wrapped leader texts at about 60 columns."""
    out, line = [], ""
    for w in text.split():
        if line and len(line) + 1 + len(w) > 60:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}" if line else w
    if line:
        out.append(line)
    return "\n".join(out)
