# Syntax – The command-driven, AI-powered sequencer

(Syntax is the code name for this project, called py-chat-midi in the project)

Overall Design Rules:

1. Syntax is a command driven. The user can use a mouse if they like but everything should be modifiable with a command. When thinking of new features keep command control in mind
2. Commands should be concise and easy to remember. Aim for a maximum of 3 words per command.
3. Commands need to have a logical and consistent structure to make them easy to remember
4. The UI should be generally read-only. Trying to combine things done via UI and commands is hard. Let's not do it
5. The UI should be mostly static in that elements stay in place as the music moves with a "window" into what's happening.
6. You should be able to manipulate the UI through logical command and macros